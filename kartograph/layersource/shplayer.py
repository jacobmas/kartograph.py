from copy import deepcopy
from layersource import LayerSource
from kartograph.errors import *
from kartograph.geometry import BBox, create_feature
from kartograph.geometry.utils import geom_to_bbox
from os.path import exists
from osgeo.osr import SpatialReference
import pyproj
from shapely.geometry import MultiPoint, Point

import shapefile
#import string


verbose = False


class ShapefileLayer(LayerSource):
    """
    this class handles shapefile layers
    """

    def __init__(self, src):
        """
        initialize shapefile reader
        """
        if isinstance(src, unicode):
            src = src.encode('ascii', 'ignore')
        src = self.find_source(src)
        self.shpSrc = src
        self.sr = shapefile.Reader(src)
        self.recs = []
        self.intersect_tol=.3
        self.max_area_for_circle=.002
        self.high_exp_factor=1.75
        self.shapes = {}
        self.geoms = {}
        self.load_records()
        self.proj = None
        # Check if there's a spatial reference
        prj_src = src[:-4] + '.prj'
        if exists(prj_src):
            prj_text = open(prj_src).read()
            srs = SpatialReference()
            wkt_ret=srs.ImportFromWkt(prj_text)
           # print 'prj_text={0}'.format(prj_text)
            #print "srs={0}".format(srs)
            if wkt_ret:
                raise ValueError("Error importing PRJ information from: %s" % prj_file)
            if srs.IsProjected():
                export_srs=srs.ExportToProj4()
              #  print 'srs.IsProjected'
                #print "Groomp"
#                self.proj=pyproj.Proj(proj='utm',zone=10,ellps='WGS84')
                self.proj = pyproj.Proj(export_srs)
            else:
                self.proj = None
               # print 'self.proj = None'
                #export_srs=srs.ExportToProj4()
                #self.proj=pyproj.Proj(init='epsg:26915')
                #self.proj = pyproj.Proj(export_srs)
        
        else:
            print 'choo'
            #self.proj=pyproj.Proj(proj='utm',zone=10,ellps='GRS80')
           #   
            #self.proj = pyproj.Proj(init='epsg:26915')

    def load_records(self):
        """
        ### Load records
        Load shapefile records into memory (but not the shapes).
        """
        self.recs = self.sr.records()
        self.attributes = []
        for a in self.sr.fields[1:]:
            self.attributes.append(a[0])
        i = 0
        self.attrIndex = {}
        for attr in self.attributes:
            self.attrIndex[attr] = i
            i += 1

    def get_shape(self, i):
        """
        ### Get shape
        Returns a shape of this shapefile. If the shape is requested for the first time,
        it will be loaded from the shapefile. Otherwise it will loaded from cache.
        """
        if i in self.shapes:  # check cache
            shp = self.shapes[i]
        else:  # load shape from shapefile
            shp = self.shapes[i] = self.sr.shapeRecord(i).shape
        return shp

    def get_geom(self, i, ignore_holes=False, min_area=0, bbox=None, proj = None):
        """ Get shape
        Returns a geom for this shapefile. If the geom is requested for the first time,
        it will be loaded via shape2geometry. Otherwise it will loaded from cache.
        """
        if i in self.geoms:  # check cache
            geom = self.geoms[i]
        else:  # load shape from shapefile
            geom = self.geoms[i] =shape2geometry(self.get_shape(i), ignore_holes=ignore_holes, min_area=min_area, bbox=bbox, proj=self.proj)
        return geom


    def forget_shape(self, i):
        if i in self.shapes:
            self.shapes.pop(i)

            
    def get_features(self, attr=None, filter=None, bbox=None, ignore_holes=False, min_area=False, charset='utf-8',bounding=False, bounding_geom=None, contained_geom=None):
        """
        ### Get features
        """
        res = []
    
        max_intersect=0
        #if contained_geom is None:
        #    print '\t\tcontained_geom is None'
        #if bounding_geom is None:
        #    print '\t\tbounding_geom is None'
        # We will try these encodings..
        known_encodings = ['utf-8', 'latin-1', 'iso-8859-2', 'iso-8859-15']
        try_encodings = [charset]
        for enc in known_encodings:
            if enc != charset:
                try_encodings.append(enc)
        # Eventually we convert the bbox list into a proper BBox instance
        if bbox is not None and not isinstance(bbox, BBox):
            bbox = BBox(bbox[2] - bbox[0], bbox[3] - bbox[1], bbox[0], bbox[1])
        ignored = 0
        #print 'len(self.recs)={0}'.format(len(self.recs))
        for i in range(0, len(self.recs)):
            # Read all record attributes
            drec = {}
            for j in range(len(self.attributes)):
                drec[self.attributes[j]] = self.recs[i][j]
            # For each record that is not filtered..
            is_nameless=True
            the_feat_name=''
#            print drec
            if 'NAME' in drec:
                the_feat_name=drec['NAME']
            elif 'FULLNAME' in drec:
                the_feat_name=drec['FULLNAME']
            if len(the_feat_name.strip())>0:
                is_nameless=False
            desired_geom=False
            drec['DESIRED_GEOM']=False
    
            if bounding_geom is not None:
                # Check if we want it to intersect
                shp=self.get_shape(i)
                shp.bounding=bounding
                shp.the_feat_name=the_feat_name
                geom = self.get_geom(i,ignore_holes=ignore_holes, min_area=min_area, bbox=bbox, proj=self.proj)
    #(shape2geometry(shp, ignore_holes=ignore_holes, min_area=min_area, bbox=bbox, proj=self.proj)
                if geom is None:
                    ignored += 1
                    continue
                intersect_geom=bounding_geom.intersection(geom)
               # if intersect_geom.area>0:
               #     print 'intersect_geom.area={0}'.format(intersect_geom.area)
                if intersect_geom.area>=self.intersect_tol*geom.area:
                    desired_geom=True
                   # print 'Found intersecting feature {0}'.format(the_feat_name)
            # Check for sufficient intersection to add places automatically
                drec['DESIRED_GEOM']=desired_geom
            if filter is None or filter(drec):
                #if contained_geom is not None:
                 #   print '\tIn for the_feat_name {0}'.format(drec['NAME'])
                props = {}
                # ..we try to decode the attributes (shapefile charsets are arbitrary)
                for j in range(len(self.attributes)):
                    val = self.recs[i][j]
                    decoded = False
                    if isinstance(val, str):
                        for enc in try_encodings:
                            try:
                                val = val.decode(enc)
                                decoded = True
                                break
                            except:
                                if verbose:
                                    print 'warning: could not decode "%s" to %s' % (val, enc)
                        if not decoded:
                            raise KartographError('having problems to decode the input data "%s"' % val)
                    if isinstance(val, (str, unicode)):
                        val = val.strip()
                    props[self.attributes[j]] = val


                if bounding_geom is not None:
#                    print 'type(bounding_geom)={0}'.format(type(bounding_geom))
                    x=bounding_geom.intersection(geom)
                    if x.area<self.intersect_tol*geom.area:
                        #print 'Name: {0} does not intersect'.format(shp.the_feat_name)
                        ignored += 1
                        self.forget_shape(i)
                        continue
                    else:
                        ignored+=0
#                        print 'Name: {0} intersects'.format(shp.the_feat_name)      
                else:
                    # If we didn't already set the shape and geom above, we set it here instead
                    shp = self.get_shape(i)
                    shp.bounding=bounding
                    shp.the_feat_name=the_feat_name
                # ..and convert the raw shape into a shapely.geometry
                    geom = self.get_geom(i,ignore_holes=ignore_holes, min_area=min_area, bbox=bbox, proj=self.proj)
                    #shape2geometry(shp, ignore_holes=ignore_holes, min_area=min_area, bbox=bbox, proj=self.proj)
                    if geom is None:
                        ignored += 1
                        continue
                    
            
                if contained_geom is not None:
                    # Add a circle if no good at the end after we get all the good features
                    #print 'Checking county {0}'.format(drec['NAME'])
                    # Find if it's the most intersecting of the geometries with
                    # contained_geom (which should really be contained_geom but haven't
                    # changed yet)
                    curr_intersect=contained_geom.intersection(geom)
                    if curr_intersect.area==0:
                       # print '\tfail: curr_intersect.area={0}'.format(curr_intersect.area)
                        ignored += 1
                        self.forget_shape(i)
                        #continue
                    else:
                        # Set this to be the new intersection level
                        #print '\tNew largest area intersection, area={0}'.format(curr_intersect.area)
                        max_intersect = curr_intersect.area
                        feature = create_feature(geom, props)
                        
                        res.append(feature)
                        #continue
                else:
                    #print 'Constructing feature {0}'.format(drec['NAME'])
                    feature = create_feature(geom, props)
                    self.feature = feature
                    res.append(feature)
        if bbox is not None and ignored > 0 and verbose:
            print "-ignoring %d shapes (not in bounds %s )" % (ignored, bbox)
        #self.proj=None
#        print 'res={0}'.format(res)

        # Add a feature consisting of a circle around the contained_geom if it's too small
        # if contained_geom is not None and bounding_geom is None:
        #     highlight_circ=self.get_highlight_circle(res, contained_geom)
        #     if highlight_circ is not None:
        #         #print('\tAdding a highlight_circ')
        #         # Create and append feature
        #         curr_props={'STATEFP':'00', 'COUNTYFP': '000', 'NAME': 'HighlightThePlace'}
        #         feature=create_feature(highlight_circ, curr_props)
        #         res.append(feature)
        return res

    '''Get the buffer circle highlighting where the contained_geom is if it's quite small
        res is a list of features (geom and props), contained_geom is the geometry, None if 
    it's not necessary
    '''

    
    # get a feature for the main geometry (to get the props too)
    def get_main_feat(self, attr=None, main_filter=None, bbox=None, ignore_holes=False, min_area=False, charset='utf-8',bounding=False):
        """
        ### Get features
        """
        result = None
        # We will try these encodings..
        known_encodings = ['utf-8', 'latin-1', 'iso-8859-2', 'iso-8859-15']
        try_encodings = [charset]
        for enc in known_encodings:
            if enc != charset:
                try_encodings.append(enc)
        # Eventually we convert the bbox list into a proper BBox instance

        ignored = 0
        # Read all record attributes
        drec = {}
        for i in range(0, len(self.recs)):
            for j in range(len(self.attributes)):
                drec[self.attributes[j]] = self.recs[i][j]
            # For each record that is not filtered..
            is_nameless=True
            the_feat_name=''
            if 'NAME' in drec:
                the_feat_name=drec['NAME']
            elif 'FULLNAME' in drec:
                the_feat_name=drec['FULLNAME']
            if len(the_feat_name.strip())>0:
                is_nameless=False
            if main_filter is None or main_filter(drec): 
               
                sq_miles_water=drec['AWATER']/(640*4046.86)
#                if sq_miles_water>=1:
#                    print 'Name: {0}\t{1:.2f} sq miles'.format(the_feat_name, sq_miles_water)
                props = {}
                # ..we try to decode the attributes (shapefile charsets are arbitrary)
                for j in range(len(self.attributes)):
                    val = self.recs[i][j]
                    decoded = False
                    if isinstance(val, str):
                        for enc in try_encodings:
                            try:
                                val = val.decode(enc)
                                decoded = True
                                break
                            except:
                                if verbose:
                                    print 'warning: could not decode "%s" to %s' % (val, enc)
                        if not decoded:
                            raise KartographError('having problems to decode the input data "%s"' % val)
                    if isinstance(val, (str, unicode)):
                        val = val.strip()
                    props[self.attributes[j]] = val

# Read the shape from the shapefile (can take some time..)..
                shp = self.get_shape(i)
                shp.bounding=bounding
                shp.the_feat_name=the_feat_name
                geom = shape2geometry(shp, ignore_holes=ignore_holes, min_area=min_area, bbox=bbox, proj=self.proj)
                feat = create_feature(geom, props)
               # ..and return the geom of the place we wanted 
                return feat
        #self.proj=None
        #print 'res={0}'.format(res)
        raise KartographError('having problems with main feature') 
        return None

# # shape2geometry


def shape2geometry(shp, ignore_holes=False, min_area=False, bbox=False, proj=None):
    if shp is None:
        return None
    if bbox and shp.shapeType != 1:
        if proj:
            left, top = proj(shp.bbox[0], shp.bbox[1], inverse=True)
            right, btm = proj(shp.bbox[2], shp.bbox[3], inverse=True)
        else:
            left, top, right, btm = shp.bbox
        sbbox = BBox(left=left, top=top, width=right - left, height=btm - top)
        if not bbox.intersects(sbbox):
            # ignore the shape if it's not within the bbox
            return None

    if shp.shapeType in (5, 15):  # multi-polygon
        geom = shape2polygon(shp, ignore_holes=ignore_holes, min_area=min_area, proj=proj)
    elif shp.shapeType in (3, 13):  # line
        geom = shape2line(shp, proj=proj)
    elif shp.shapeType == 1: # point
        geom = shape2point(shp, proj=proj)
    else:
        raise KartographError('unknown shape type (%d)' % shp.shapeType)
    return geom


def shape2polygon(shp, ignore_holes=False, min_area=False, proj=None):
    """
    converts a shapefile polygon to geometry.MultiPolygon
    """
   # ignore_holes=True
    
    # from kartograph.geometry import MultiPolygon
    from shapely.geometry import Polygon, MultiPolygon
    from kartograph.geometry.utils import is_clockwise
    parts = shp.parts[:]
    parts.append(len(shp.points))
    exteriors = []
    rep_point = None
    holes = []
#    print 'shp.the_feat_name={0}'.format(shp.the_feat_name)
#    print 'shp.represenative_points={0}'.format(shp.representative_point())
    for j in range(len(parts) - 1):
        pts = shp.points[parts[j]:parts[j + 1]]
        if shp.shapeType == 15:
            # remove z-coordinate from PolygonZ contours (not supported)
            for k in range(len(pts)):
                pts[k] = pts[k][:2]
        if proj and shp.alreadyProj is False:
            project_coords(pts, proj, rep_point=rep_point)
            if shp.bounding:
#                print 'Already proj, proj exists'
                shp.alreadyProj=True
        elif shp.alreadyProj is False:
            if shp.bounding:
                shp.alreadyProj=True
            #else:
             #   print 'shp.bounding={0}'.format(shp.bounding)
 #           print 'Already proj, no proj exists'
        cw = is_clockwise(pts)
        if cw:
            exteriors.append(pts)
        else:
            holes.append(pts)
    if ignore_holes:
        print 'ignoring holes'
        holes = None
#    if len(holes) > 0:
#        print '\tThere are {0} holes'.format(len(holes))
    if len(exteriors) == 1:
 #       print 'Single polygon, {0}'.format(shp.the_feat_name)
        poly = Polygon(exteriors[0], holes)
    elif len(exteriors) > 1:
#        print 'Multipolygon, {0}'.format(shp.the_feat_name)
        # use multipolygon, but we need to assign the holes to the right
        # exteriors
        from kartograph.geometry import BBox
        used_holes = set()
        polygons = []
        for ext in exteriors:
            bbox = BBox()
            my_holes = []
            for pt in ext:
                bbox.update(pt)
            for h in range(len(holes)):
                if h not in used_holes:
                    hole = holes[h]
                    if bbox.check_point(hole[0]):
                        # this is a very weak test but it should be sufficient
                        used_holes.add(h)
                        my_holes.append(hole)
            polygons.append(Polygon(ext, my_holes))
        if min_area:
            # compute maximum area
            max_area = 0
            for poly in polygons:
                max_area = max(max_area, poly.area)
            # filter out polygons that are below min_area * max_area
            polygons = [poly for poly in polygons if poly.area >= min_area * max_area]
        poly = MultiPolygon(polygons)
    else:
#        return None
        raise KartographError('shapefile import failed - no outer polygon found')
#    print 'poly={0}'.format(poly)
    return poly


def shape2line(shp, proj=None):
    """ converts a shapefile line to geometry.Line """
    from shapely.geometry import LineString, MultiLineString

    parts = shp.parts[:]
    parts.append(len(shp.points))
    lines = []
    for j in range(len(parts) - 1):
        pts = shp.points[parts[j]:parts[j + 1]]
        if shp.shapeType == 13:
            # remove z-coordinate from PolylineZ contours (not supported)
            for k in range(len(pts)):
                pts[k] = pts[k][:2]
        if proj:
            project_coords(pts, proj)
        lines.append(pts)
    if len(lines) == 1:
        return LineString(lines[0])
    elif len(lines) > 1:
        return MultiLineString(lines)
    else:
        raise KartographError('shapefile import failed - no line found')

def shape2point(shp, proj=None):
    from shapely.geometry import MultiPoint, Point
    points = shp.points[:]
    if len(points) == 1:
        return Point(points[0])
    elif len(points) > 1:
        return MultiPoint(points)
    else:
        raise KartographError('shapefile import failed - no points found')
    
  
def project_coords(pts, proj, rep_point=None):
    from shapely.geometry import Polygon, MultiPolygon
    for i in range(len(pts)):
        x, y = proj(pts[i][0], pts[i][1], inverse=True)
        pts[i][0] = x
        pts[i][1] = y


def get_scale_offset(pts, proj,  scale):
    from shapely.geometry import Polygon, MultiPolygon
    pts2=deepcopy(pts)
    pts3=deepcopy(pts)
    for i in range(len(pts2)):
        if proj:
            x, y = proj(pts2[i][0], pts2[i][1], inverse=True)
        else:
            x, y = pts2[i][0], pts2[i][1]
        pts2[i][0]=x
        pts2[i][1]=y
        pts3[i][0]=x*scale
        pts3[i][1]=y*scale
    
    poly2=Polygon(pts2,None)
    poly3=Polygon(pts3,None)
    
    center2=poly2.centroid
    center3=poly3.centroid
    diff_lat=(center2.x-center3.x)
    diff_lon=(center2.y-center3.y)
    return (diff_lat, diff_lon)
#    diff_lat2 = pts2[0][0]-pts3[0][0]
 #   diff_lon2 = pts2[0][1]-pts3[0][1]
#    return (diff_lat2, diff_lon2)
