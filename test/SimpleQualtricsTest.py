#!/usr/bin/env python
# coding: utf-8

# ## SimpleQualtrics Test
# 
# Tests for the SimpleQualtrics module. Tests API calls, logging and timeout handling.

# In[1]:


import SimpleQualtrics
import pandas as pd
from unittest import TestCase
import unittest
import pytest
import responses
from tempfile import TemporaryDirectory
import os
import requests
import io, zipfile
import logging
from pandas.testing import assert_frame_equal
import sys

# uncomment to show simulated calls made (except in logging tests)
logging.basicConfig(level=logging.DEBUG) 


# In[2]:


class TestConfiguration(TestCase):
    def test_successful_parameter_configuration(self):
        qq=SimpleQualtrics.Session(token='t', dataCenter='d')
        self.assertEqual(qq.config('token'),'t')
        self.assertEqual(qq.config('notPresent','u'),'u')
        with pytest.raises(KeyError):
            qq.config('notPresent')
            
    def test_incomplete_configuration(self):
        with pytest.raises(AssertionError):
            SimpleQualtrics.Session(token='t')
            
    def test_parameters_from_yaml(self):
        with TemporaryDirectory() as tempDir: # NamedTemporaryFile is inconsistent across OSs
            filename=os.path.join(tempDir, 'config.yaml')
            with open(filename,'w') as f:
                f.write('token: t\ndataCenter: d\nextra: e')
            qq=SimpleQualtrics.Session(yaml=filename)
            self.assertEqual(qq.config('extra'),'e')
        
    def test_missing_yaml(self):
        with pytest.raises(FileNotFoundError):
            SimpleQualtrics.Session(yaml='nonExistentFile')

def setupFileResponse(fileContents, relPath, params):
        ''' Sets up the mock responses for a file download, answering fileContents'''
        byteStream=io.BytesIO()
        with zipfile.ZipFile(byteStream,'w') as zipThing:
            zipThing.writestr('ignoredName',fileContents)
        
        responses.add(responses.POST, 'https://d.qualtrics.com/API/v3/{}'.format(relPath),
                    match=[responses.json_params_matcher(params)],
                    json={'result': {'progressId': 'theId'}})
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/{}/theId'.format(relPath),
                    json={'result': {'status': 'in progress'}})
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/{}/theId'.format(relPath),
                    json={'result': {'status': 'complete', 'fileId': 'theId'}})
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/{}/theId/file'.format(relPath),
                    body=byteStream.getvalue())
        
class TestAPICalls(TestCase):
    def setUp(self):
        self.q=SimpleQualtrics.Session(token='t', dataCenter='d',
                    fileCreationPollIntervalMillis=0)
          
    @responses.activate
    def test_call(self):
        # Check logging and basic requests work OK:
        with self.assertLogs(level='INFO') as logs:
            responses.add(responses.PUT, 'https://a',
                      match=[responses.json_params_matcher({'a':'a'})])
            self.q.put('https://a', {'a':'a'}) # Use PUT as the simplest with params
        self.assertEqual(len(logs.output), 1)
        self.assertRegex(logs.output[0], "SimpleQualtrics.*https://a.*\{'a': 'a'\}")
    
    @responses.activate
    def test_get(self):
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello',
                  json={'result': 'theResult'})
        self.assertEqual(self.q.get('hello'), 'theResult')

    @responses.activate
    def test_qualtrics_error(self):
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello', status=400,
                  json={'meta': {'error': {'errorMessage': 'wrong'}}}) 
        with pytest.raises(SimpleQualtrics.QualtricsError) as excinfo:
            self.q.get('hello') 
        excinfo.match('wrong')
        self.assertRegex(excinfo.exconly(), 'QualtricsError') # The default display of the error.
    
    @responses.activate
    def test_qualtrics_500_and_error_logging(self):
        # Server returns same json format for a 500 error. And we want to check errors are logged.
        with self.assertLogs(level='INFO') as logs:
            responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello', status=500,
                  json={'meta': {'error': {'errorMessage': 'wrong2'}}}) 
            with pytest.raises(SimpleQualtrics.QualtricsError) as excinfo:
                self.q.get('hello') 
            excinfo.match('wrong2')
        self.assertEqual(len(logs.output), 2)
        self.assertRegex(logs.output[1], "ERROR:.*SimpleQualtrics:QualtricsError.*wrong2")


    @responses.activate
    def test_timeout(self):
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello',
                      body=requests.Timeout())
        with pytest.raises(requests.Timeout):
            self.q.get('hello')
            
    @responses.activate
    def test_get_multiple(self):
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello',
                  json={'result': {'elements': ['page 1'], 'nextPage': 'https://b'}})
        responses.add(responses.GET, 'https://b',
                  json={'result': {'elements': ['page 2'], 'nextPage': None}})
        self.assertEqual(self.q.getMultiple('hello'), ['page 1', 'page 2'])
     
    @responses.activate
    def test_get_multiple_no_paging(self):
        # E.g. /tickets (no, probably /activities)
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello',
                  json={'result': {'elements': ['page 1']}})
        self.assertEqual(self.q.getMultiple('hello'), ['page 1'])

    @responses.activate
    def test_post(self):
        responses.add(responses.POST, 'https://d.qualtrics.com/API/v3/hello',
                    match=[responses.json_params_matcher({'a':'a'})],
                    json={'result': {'r': 'r'}}) 
        self.assertEqual(self.q.post('hello', {'a': 'a'}), {'r': 'r'})
        
    @responses.activate
    def test_post_create(self):
        responses.add(responses.POST, 'https://d.qualtrics.com/API/v3/hello',
                    match=[responses.json_params_matcher({'a':'a'})],
                    json={'result': {'doesntMatter': 'theId'}}) # the key used for the id returned varies.
        self.assertEqual(self.q.postCreate('hello', {'a': 'a'}), 'theId')
    
    @responses.activate
    def test_delete(self):
        responses.add(responses.DELETE, 'https://d.qualtrics.com/API/v3/hello')
        self.q.delete('hello')
        
    @responses.activate
    def test_put(self):
        responses.add(responses.PUT, 'https://d.qualtrics.com/API/v3/hello', 
                     match=[responses.json_params_matcher({'a':'a'})])
        self.q.put('hello', {'a': 'a'})
       
    
        
    @responses.activate
    def test_file_from_post(self):
        setupFileResponse('Hello world', 'hello', {'a':'a'} )
        f = self.q.fileFromPost('hello', {'a':'a'})
        self.assertEqual(f.read(), b'Hello world')

    @responses.activate
    def test_file_from_post_timeout(self):
        qq=SimpleQualtrics.Session(token='t', dataCenter='d', fileCreationTimeout=0)
        setupFileResponse('contents will not be returned', 'hello', {'a':'a'})
        with pytest.raises(requests.Timeout) as excinfo:
            qq.fileFromPost('hello', {'a':'a'})
        excinfo.match('Qualtrics.*[Tt]imeout')
  
    @responses.activate
    def test_file_from_post_bad_status(self):  
        responses.add(responses.POST, 'https://d.qualtrics.com/API/v3/hello',
                        json={'result': {'id': 'theId'}})
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/hello/theId',
                        json={'result': {'status': 'failed'}})
        with pytest.raises(SimpleQualtrics.QualtricsError) as excinfo:
            self.q.fileFromPost('hello', {'a':'a'}) 
        excinfo.match('failed')
        

if 'ipykernel' in sys.modules:
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
elif __name__ == '__main__':
        unittest.main()

