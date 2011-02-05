#!/usr/bin/env python

import wsgiref.handlers
from google.appengine.ext import webapp

# Please see comments in BackupFlickr/__init__.py

import BackupFlickr

if __name__ == '__main__':

  handlers = [
    ('/', BackupFlickr.MainApp),
    ('/get_photos', BackupFlickr.GetPhotos),
    ('/get_info', BackupFlickr.GetFlickrInfo),
    ('/get_photo_info', BackupFlickr.GetPhotoInfo),
    ('/backup_photo', BackupFlickr.BackupPhoto),
    ('/img/([^/]+)?', BackupFlickr.ServeImg),    
    ('/receive_blob', BackupFlickr.BlobReceive),
    ('/signout', BackupFlickr.Signout),
    ('/signin', BackupFlickr.Signin),    
    ('/auth', BackupFlickr.TokenDance),
    ]

  application = webapp.WSGIApplication(handlers, debug=True)
  wsgiref.handlers.CGIHandler().run(application)
