# SimpleQualtrics implementation
#
# Copyright (c) 2020 Charles Weir
# Released as open source - see licence.

import requests
import zipfile
import io
import yaml # PyYAML
from string import Template
import time
import logging
import re
from collections import OrderedDict

class QualtricsError(requests.RequestException):
    '''The Qualtrics server returned an error'''


class SimpleQualtrics(object):
    ''' This class handles simple access to Qualtrics V3 APIs. It implements credentials,
    configuration handling, choice of API server, practical error handling, call timeouts,
    call logging, and Python-friendly decoding of Qualtrics response formats and protocols.
    '''
    
    def __init__(self, **kwargs):
        '''
        Keyword parameters are added as configuration items to the configuration database, except::
        
            SimpleQualtrics(yaml='filename.yaml')
            
        loads configuration from the given file.
        
        The required configuration parameters are:
             **token**
                the Qualtrics API token
             **dataCenter**
                the Qualtrics center ID to use)
     '''
                               
        self.configDb=kwargs
        self.logger = logging.getLogger(__name__)
        if 'yaml' in self.configDb:
            with open(self.configDb['yaml']) as f:
                self.configDb.update(yaml.safe_load(f))
        assert all(k in self.configDb for k in ('token', 'dataCenter')), 'Need both token and dataCenter in SimpleQualtrics configuration'
        self.requestsParameters={
            'headers': {'x-api-token': self.config('token')},
            'timeout': self.config('timeout',30)}
        self.baseUrl = 'https://{}.qualtrics.com/API/v3/'.format(self.config('dataCenter'))

    def config(self, item, default=None):
        ''' Answer the configuration entry for the given item, else a default if provided
        
        :param item: The configuration item
        :type item: String
        :param default: Default value if the item is not in the configuration database
        :type default: String
        :rtype: String
        :raises KeyError: if `item` is not found and no default is present
        '''
        return self.configDb[item] if default == None else self.configDb.get(item,default)
        
    # The basic Qualtrics CRUD API calls. We ignore metadata returned (except for error messages).
    
    def get(self, relPath):
        ''' Make a GET request that answers a single structure as a Python dictionary.
        
        :param relPath: The relative path for the API request
        :type relPath: String
        :rtype: Dictionary
        
        :raises QualtricsError, requests.RequestException:
        '''
        r=self.call('GET', relPath)
        return r.json()['result']
        
    def post(self, relPath, parameters):
        ''' Make a POST request that returns a single structure as a Python dictionary.
        
        :param relPath: The relative path for the API request
        :type relPath: String
        :param parameters: keyword parameters to pass with the request
        :type parameters: Dictionary of string pairs
        :rtype: Dictionary
        
        :raises QualtricsError, requests.RequestException:
        '''
        r=self.call('POST', relPath, json=parameters)
        return r.json()['result']
    
    def put(self, relPath, parameters):
        ''' Call PUT for the given path and parameters
        
        :param relPath: The relative path for the API request
        :type relPath: String
        :param parameters: keyword parameters to pass with the request
        :type parameters: Dictionary of string pairs
 
        :raises QualtricsError, requests.RequestException:
        '''
        self.call('PUT', relPath, json=parameters)
        
    def delete(self, relPath):
        '''Call DELETE for the given path
        
        :param relPath: The relative path for the API request
        :type relPath: String
        
        :raises QualtricsError, requests.RequestException:
        '''
        self.call('DELETE', relPath)

    # A convenience wrapper around .post:
        
    def postCreate(self, relPath, parameters):
        ''' Do the specified post, answering the string id of the object created where this is the only entry in the results or
        where it contains one of the possibleIdFields fields, else `None`.
        
        :param relPath: The relative path for the API request
        :type relPath: String
        :param parameters: keyword parameters to pass with the request
        :type parameters: Dictionary of string pairs
        :rtype: String or None
        
        :raises QualtricsError, requests.RequestException:
        '''
        possibleIdFields=['progressId']
        result=self.post( relPath, parameters)
        
        return next((result[key] for key in result)) if len(result) == 1 else next(
                               (result[field] for field in possibleIdFields if field in result), None)
        
    # More complex operations, involving multiple related calls:
    
    def getMultiple(self, relPath):
        ''' Make a GET request that returns an array of structures, implementing paging if the API uses it.
        
        :param relPath: The relative path for the initial API request
        :type relPath: String
        :rtype: List of Dictionaries.
        
        :raises QualtricsError, requests.RequestException:
        
        Use the return value as constructor parameter to create a Pandas DataFrame.'''
        elements=[]
        while True:
            r=self.call('GET', relPath)
            result=r.json()['result']
            elements = elements + result['elements']
            relPath=result.get('nextPage') # May not be present. e.g. /logs/activitytypes
            if relPath == None:
                break
        return elements

    def fileFromPost(self, relPath, parameters):
        '''Answer a filestream containing the result of the given request for a responses file.
        Supports both legacy and newer downloading of responses.
        
        :param relPath: The relative path for the initial API request
        :type relPath: String
        :param parameters: keyword parameters to pass with the initial request
        :type parameters: Dictionary of string pairs
        :rtype: IOStream
        
        :raises QualtricsError, requests.RequestException:
        
        Note that the filestream supports `seek()`, which allows it to be read more than once.
        '''
    
        requestId=self.postCreate(relPath, parameters)
        startTime=time.monotonic()
        while True:
            statusResponse=self.get(relPath + '/' + requestId)
            status=statusResponse['status']
            if status == 'complete':
                break
            if not 'progress' in status.lower(): # 'in progress' and 'inProgress' have both been seen
                raise QualtricsError('File creation status: ' + status )
            if time.monotonic() - startTime >= self.config('fileCreationTimeout', self.requestsParameters['timeout']):
                raise requests.Timeout('Qualtrics timeout preparing file download')
            time.sleep(self.config('fileCreationPollIntervalMillis',500)/1000) # Don't want to DOS the Qualtrics server.
            
        r=self.call('GET', relPath + '/{}/file'.format( statusResponse['fileId'] if 'fileId' in statusResponse else requestId))
        surveyZip=zipfile.ZipFile(io.BytesIO(r.content))
        return surveyZip.open(surveyZip.infolist()[0].filename)
    
    
    # And the underlying operation used for all calls:
    
    def call(self, action, url, **kwargs):
        ''' Make an https call to url,
        with the appropriate Qualtrics headers, logging and timeout, answering a `requests.Result` object.
        
        :param action: A `requests` action, such as 'POST'
        :type action: String
        :param url: Either the relative path for API request, or the full path starting 'http'...
        :type url: String
        :param kwargs: keyword parameters to pass with the request
        :type kwargs: Dictionary of string pairs
        :rtype: `requests.Result`
        
        :raises QualtricsError, requests.RequestException:
        
        Use *json={someParameters}* to pass parameters to a POST or PUT
        
        '''
        
        url=url if url.startswith('https://') else self.baseUrl + url
        self.logger.info('{} {}{}'.format(action, url, (' with payload: ' + str(kwargs['json']) if 'json' in kwargs else '')))
        r=requests.request(action, url, **self.requestsParameters, **kwargs)
        try:
            if 400 <= r.status_code <= 500: # Qualtrics returns its error messages in the JSON:
                raise QualtricsError(r.json()['meta']['error']['errorMessage'], response=r)
            r.raise_for_status()
        except requests.RequestException as e:
            self.logger.error(repr(e))
            raise
        return r

