runserver: 
	python2.5 /usr/local/google_appengine/dev_appserver.py .
deploy : 
	python2.5 /usr/local/google_appengine/appcfg.py update .

clean :
	find . -name \*.pyc | xargs -n 100 rm
