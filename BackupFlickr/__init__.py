# http://github.com/straup/gae-flickrapp/tree/master

from FlickrApp import FlickrApp
from FlickrApp.Tables import dbFlickrUser
import simplejson
import urllib2_file
import urllib2, urllib
from cStringIO import StringIO
import os
import logging
import math
import httplib, mimetypes
from urllib2_file import UploadFile
import blogstore_helper
 
from google.appengine.api.urlfetch import ResponseTooLargeError, DownloadError
from google.appengine.ext.webapp.util import login_required
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.api import taskqueue
from google.appengine.ext.webapp import template
from google.appengine.api import images

from config import config

def smart_str(s, encoding='utf-8', strings_only=False, errors='strict'):
    """
    Returns a bytestring version of 's', encoded as specified in 'encoding'.
    If strings_only is True, don't convert (some) non-string-like objects.
    """
    if strings_only and isinstance(s, (types.NoneType, int)):
        return s
    if isinstance(s, str):
        return unicode(s).encode(encoding, errors)
    elif not isinstance(s, basestring):
        try:
            return str(s)
        except UnicodeEncodeError:
            if isinstance(s, Exception):
                # An Exception subclass containing non-ASCII data that doesn't
                # know how to print itself properly. We shouldn't raise a
                # further exception.
                return ' '.join([smart_str(arg, encoding, strings_only,
                        errors) for arg in s])
            return unicode(s).encode(encoding, errors)
    elif isinstance(s, unicode):
        return s.encode(encoding, errors)
    elif s and encoding != 'utf-8':
        return s.decode('utf-8', errors).encode(encoding, errors)
    else:
        return s


class Photo(db.Model):
    user = db.UserProperty()
    flickrUser= db.ReferenceProperty(dbFlickrUser)
    backed_up = db.BooleanProperty()
    blob = blobstore.BlobReferenceProperty()
    photo_id = db.StringProperty()
    json = db.TextProperty()
    date = db.DateTimeProperty(auto_now_add=True)



class BackupFlickrApp (FlickrApp) :
    def __init__ (self) :
        FlickrApp.__init__(self, config['flickr_apikey'], config['flickr_apisecret'])
        self.flickr = FlickrApp
        self.config = config
        self.min_perms = config['flickr_minperms']


class MainApp(BackupFlickrApp) :

    @login_required
    def get (self) :

        user = users.get_current_user()

        if not self.check_logged_in(self.min_perms) :
            self.response.out.write("<a href=\"/signin\">Click here to sign in using Flickr</a>")
            return

        photos = Photo.all()
        photos.filter("user = ", user)
        photos.filter("backed_up = ", True)
        photos.order('-photo_id')
        photos = photos.fetch(200)

        
        not_backedup_photos = Photo.all()
        not_backedup_photos.filter("backed_up != ", True)
        not_backedup_photos.filter("user = ", user)

        crumb = self.generate_crumb(self.user, 'logout')
        path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
        self.response.out.write(template.render(path, {'crumb':crumb,'photos':photos,'not_backedup_photos':not_backedup_photos}))
        return

class GetFlickrInfo(BackupFlickrApp) :

    @login_required
    def get (self) :

        if not self.check_logged_in(self.min_perms) :
            self.response.out.write("<a href=\"/signin\">Click here to sign in using Flickr</a>")
            return

        user = users.get_current_user()

        crumb = self.generate_crumb(self.user, 'logout')
        api = self.api
        Flickr = self.Flickr
        token = self.user.token
        per_page = config['per_page']
        # flickr.activity.userPhotos (requires authentication):
        #photos_rsp = api.execute_request(Flickr.API.Request(method='flickr.people.getPhotos', auth_token=token, user_id='me', format='json', nojsoncallback=1, per_page=per_page))

        if not self.user.count:
            info_rsp = api.execute_request(Flickr.API.Request(method='flickr.people.getInfo', auth_token=token, user_id=self.user.nsid, format='json', nojsoncallback=1))
            if info_rsp.code == 200:
                info = simplejson.loads(info_rsp.read())
                photo_count = info['person']['photos']['count']['_content']
                self.user.count = photo_count
                self.user.save()

        pages = int(math.ceil(float(self.user.count) / per_page))
        self.user.pages = pages
        if not self.user.current_page:
            self.user.current_page = 0 
        self.user.user = user
        self.user.save()
        flickr_user_key = str(self.user.key())
        task_params={
                'flickr_user_obj': flickr_user_key,
                }
        taskqueue.Task(url='/get_photos', params=task_params).add(queue_name='crawlphotos')

        self.redirect("/")
        return

class GetPhotos(BackupFlickrApp) :

    def post (self) :

        flickr_user_obj = str(self.request.POST['flickr_user_obj'])

       
        flickr_user = db.get(flickr_user_obj)
        user = flickr_user.user

        per_page = config['per_page']
        page = flickr_user.current_page
        photos_rsp = self.api.execute_request(self.Flickr.API.Request(method='flickr.people.getPhotos', auth_token=flickr_user.token, user_id='me', format='json', nojsoncallback=1, per_page=per_page, page = page))
        if photos_rsp.code == 200:
            photos = simplejson.loads(photos_rsp.read())['photos']['photo']
            for p in photos:
                photo_json = simplejson.dumps(p)
                photo = Photo()
                photo.user = user
                photo.flickrUser = flickr_user
                photo.photo_id = p['id']
                photo.save()
                photo_key = str(photo.key())
                task_params={
                        'photo_obj': photo_key,
                        'token': flickr_user.token, 
                        'page': page, 
                        'photo_json':photo_json, 
                        }
                taskqueue.Task(url='/get_photo_info', params=task_params).add(queue_name='photoinfo')
            flickr_user.current_page = page + 1
            flickr_user.save()
            task_params={
                'flickr_user_obj': flickr_user_obj,
                }
            taskqueue.Task(url='/get_photos', params=task_params, countdown=30).add(queue_name='crawlphotos',)
            return

class GetPhotoInfo(BackupFlickrApp) :
    def post(self) :
        logging.info(self.request.POST)

        photo = simplejson.loads(self.request.POST['photo_json'])
        photo_obj = str(self.request.POST['photo_obj'])
        token = self.request.POST['token']

        photo_info_rsp = self.api.execute_request(self.Flickr.API.Request(method='flickr.photos.getInfo', auth_token=token, photo_id=photo['id'], secret=photo['secret'], format='json', nojsoncallback=1))
        if photo_info_rsp.code == 200:
            photo_info = simplejson.loads(photo_info_rsp.read())['photo']

        photo_name = str(photo_info['id'])+"_"+str(photo_info['originalsecret'])+"_o."+str(photo_info['originalformat'])
        photo_url = "http://farm"+str(photo_info['farm'])+".static.flickr.com/"+str(photo_info['server'])+"/"+str(photo_info['id'])+"_"+str(photo_info['originalsecret'])+"_o."+str(photo_info['originalformat'])
        logging.info(photo_url)
        logging.info(photo_obj)

        p = db.get(photo_obj)
        p.json = simplejson.dumps(photo_info)
        p.save()

        task_params={
                    'photo_obj': photo_obj, 
                    'photo_name':simplejson.dumps(photo_name), 
                    'photo_url':photo_url, 
                    }
        taskqueue.Task(url='/backup_photo', params=task_params).add(queue_name='backupphoto')
        

    def get(self):
        print "ad"

class BackupPhoto(BackupFlickrApp) :
    def post (self) :
        photo_url = self.request.POST['photo_url']
        photo_obj = self.request.POST['photo_obj']
        photo_name = simplejson.loads(self.request.POST['photo_name'])

        try:
            photo_string = StringIO(urllib2.urlopen(photo_url).read())
        except (urllib2.HTTPError, DownloadError):
            pass

        try:
            upload_blob = UploadFile(photo_string, str(photo_name))
            upload_url = blobstore.create_upload_url('/receive_blob')

            params={
                    'photo_obj': smart_str(photo_obj), 
                    'file': upload_blob
                    }
            logging.info(params)
            try:
                urllib2.urlopen(upload_url, params)
            except:
                p = db.get(photo_obj)
                p.backed_up = False
                p.save()
                return 
            #('too big')
              
        except urllib2.URLError, e:
           print "error"
            

        return

class BlobReceive(blobstore_handlers.BlobstoreUploadHandler):

    def post (self):
        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        photo_obj = self.request.POST['photo_obj']
        blob_info = upload_files[0]
        
        p = db.get(photo_obj)
        p.backed_up = True
        p.blob = blob_info
        p.save()

        self.redirect('/')
 
class ServeImg(BackupFlickrApp):

    def get (self,entity_id):
        entity = db.get(entity_id)
        blob = entity.blob

        image_size = None
        crop = True

        try:
            if self.request.GET['size']:
                image_size = self.request.GET['size']
        except:
            pass
        
        if image_size:
            image_size = int(image_size)
        image_url = images.get_serving_url(blob_key=str(blob.key()),size=image_size, crop=crop)
        self.redirect(image_url)




class TokenDance (BackupFlickrApp) :

    def get (self):

        try :

            new_users = True
            self.do_token_dance(allow_new_users=new_users)
            
        except FlickrApp.FlickrAppNewUserException, e :
            self.response.out.write('New user signups are currently disabled.')

        except FlickrApp.FlickrAppAPIException, e :
            self.response.out.write('The Flickr API is being cranky.')

        except FlickrApp.FlickrAppException, e :
            self.response.out.write('Application error: %s' % e)
      
        except Exception, e:
            self.response.out.write('Unknown error: %s' % e)

        return
    
# This is where you send a user to sign in. If they are not
# already authed then the application will take care generating
# Flickr Auth frobs and other details.

class Signin (BackupFlickrApp) :
    
    def get (self) :
        if self.check_logged_in(self.min_perms) :
            self.redirect("/")
            
        self.do_flickr_auth(self.min_perms, '/')
        return

# This is where you send a user to log them out of your
# application. The user may or may not still be logged in to
# Flickr. Note how we're explictly zero-ing out the cookies;
# that should probably be wrapped up in a helper method...

class Signout (BackupFlickrApp) :

    def post (self) :

        if not self.check_logged_in(self.min_perms) :
            self.redirect("/")

        crumb = self.request.get('crumb')

        if not crumb :
            self.redirect("/")
            
        if not self.validate_crumb(self.user, "logout", crumb) :
            self.redirect("/")

        self.response.headers.add_header('Set-Cookie', 'ffo=')
        self.response.headers.add_header('Set-Cookie', 'fft=')    
        
        self.redirect("/")
    
