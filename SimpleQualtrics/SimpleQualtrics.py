
import requests
import zipfile
import io
import yaml
from string import Template
import time
import logging
import pandas as pd
import re
import json
from collections import OrderedDict

class QualtricsError(requests.RequestException):
    '''The Qualtrics server returned an error'''
    
class QualtricsDataError(Exception):
    '''Missing or unexpected data in Qualtrics response'''
        
class ThingWithIdAndName:
    ''' Many survey-related objects have both a name and an ID. (e.g. the Survey title and it's internal Qualtrics ID).
    The ID attribute (id) is the user visible one, NOT any internal one Qualtrics may use. '''
    
    def _className(self):
        return type(self).__name__.split('.')[-1]
    
    def _first(self, identifier, sequence):
        ''' Answers the first element in the sequence (usually a finding construct) raising an exception if there is none.
        identifier: Something to identify the problem if it is not found
        sequence: the sequence. '''
        
        result=next(sequence, None)
        if result==None:
            raise QualtricsDataError('{}: {} not found'.format(self._className(), repr(identifier)))
        return result
        
    def __repr__(self):
        return '{{{} {}: {}}}'.format(self._className(), str(self.id), self.name)
        
class Choice(ThingWithIdAndName):
    ''' One of the possible multiple choice responses to a question or sub-question'''
    def __init__(self, question, identifier):
        self._question = question
        cT = question._choiceTable()
        self.id, self.name  = self._first( identifier, ( (question._recodedChoiceId(k), cT[k]['Display']) for k in cT if
             # The criterion is a match to the external ID, if we're searching for an integer identifier
             (identifier == question._recodedChoiceId(k) if isinstance(identifier, int)
             # Or a regex match to the choice text string otherwise:
              else re.search( identifier, cT[k]['Display'] )) ) )

class SubQuestion(ThingWithIdAndName):
    ''' One of the sub-questions in a matrix question'''
    def __init__(self, question, identifier):
        self._question = question
        cT = question._subQuestionTable()
        self.id, self.name  = self._first( identifier, ( (question._externalSubQId(k), cT[k]['Display']) for k in cT if
                     (identifier == question._externalSubQId(k) if isinstance(identifier, int)
                      else re.search( identifier, cT[k]['Display'] )) ) )
                      
    def responses(self):
        ''' Answers the responses to this sub-question, as a DataFrame (if multiple choice) or Series
        The column names for multiple choice are of the format Qn_n_n '''
    
        columnNamesRegex='^{}_{:d}($|_)'.format( self._question.id, self.id )
        myResponses=self._question._survey.responses().filter(regex=columnNamesRegex)
        return myResponses.iloc[:,0] if len(myResponses.columns) == 1 else myResponses # Series if single column.

class Question(ThingWithIdAndName):
    ''' A question in the survey'''
    def __init__(self, survey, identifier):
        self._survey=survey
        regex=re.compile(identifier)
        self.id, self.name  = self._first( identifier, ( (q['DataExportTag'], q['QuestionDescription']) for q in survey._questionDefinitions() if (identifier == q['DataExportTag'] if re.match(r'Q\d+$', identifier)
                      else regex.search( q['QuestionDescription'])) ) )
    
    def _definition(self):
        # Private: Answers the Qualtrics question definition structure as returned by survey-definitions/{}/questions
        return next( q for q in self._survey._questionDefinitions() if q['DataExportTag'] == str(self.id) )
      
    def _choiceTable(self):
        # Whichever choice table the question description has, else None.
        # Usually Choices. However Matrix questions have both Answers and Choices, where matrix Choices are really sub-questions
        d=self._definition()
        return d.get('Answers') or d.get('Choices') or {}
        
    def _recodedChoiceId(self, id):
        ''' Private: Answers the actual choice id corresponding to an internal value'''
        d=self._definition()
        return int(d['RecodeValues'][id] if 'RecodeValues' in d else id)
        
    def _subQuestionTable(self):
        # Same for sub-questions:
        d=self._definition()
        return d['Choices'] if d.get('Answers') and d.get('Choices') else {}
       
    def _externalSubQId( self, internalId ):
        '''Private: Answers the externally-visible choice ID corresponding to the (string) internal value'''
        # Ouch. Syntax of the ChoiceOrder fields is not necessarily consistent. Might be string or int or even change mid way through.
        co=self._definition()['ChoiceOrder']
        return 1 + (co.index(internalId) if internalId in co else co.index(int(internalId)))
        
    def choice(self, identifier):
        ''' Answers the corresponding multiple choice choice.
        If identifier is int, answers the choice with that ID; if identifier is string answers the first choice matching that Regex anywhere in its question string.'''
        return Choice( self, identifier )
        
    def subQuestion( self, identifier ):
        ''' Answers the subQuestion matching the identifier.
        If identifier is an int, it is taken as the (external) SubQuestion ID;
        if a string, answers the first SubQuestion matching that string as a regex'''
        return SubQuestion(self, identifier)
        
    def responses(self):
        ''' Answers the responses to this question as a Series, or, if the question has subQuestions, as a DataFrame with column titles the subQuestion IDs.'''
        if self._subQuestionTable():
            raise QualtricsDataError('Question {} has subquestions'.format(self.id))
            # DataFrame with columns my subquestion IDs, values integers
        return self._survey.responses()[self.id]
 
    def subQuestions(self):
        ''' Returns a list of all the SubQuestion objects for this Question. '''
        return [self.subQuestion(self._externalSubQId(internalId)) for internalId in self._subQuestionTable()]
        
    def choices(self):
        ''' Returns a list of all Choice objects for this Question.'''
        ids =  [int(self._recodedChoiceId(id)) for id in self._choiceTable()]
        return [self.choice(id) for id in sorted(ids)]
 
 
class CurrentUser(ThingWithIdAndName):
    ''' Information about the current user'''
    def __init__(self, qs):
        self._whoami=qs.get('whoami')
        self.id = self._whoami['userId']
        self.name = ' '.join([self._whoami['firstName'], self._whoami['lastName']])
 
 
class Survey(ThingWithIdAndName):
    ''' Represents a full Qualtrics survey'''
    _ssInfo = None # The response to the /surveys API call
    
    @classmethod
    def _surveysInfo(self, sq):
        self._ssInfo=self._ssInfo or sq.getMultiple('surveys')
        return self._ssInfo
    
    @classmethod
    def all(self, sq):
        ''' Answers an array of Survey objects representing all the surveys in the account.
        '''
        return [Survey(sq, s['id']) for s in self._surveysInfo(sq)]

    def __init__(self, sq, identifier, **responsesParameters):
        '''Creates a new Survey object:
        @param sq - an initialized SimpleQualtrics object
        @param identifier - string, either the survey ID or a regex string to match the survey name
        @param responsesParameters - keyword arguments to be passed to the <POST export-responses> API call, usually to limit the set of responses returned.
        '''
        self._q = sq
        regex=re.compile(identifier)
        (self.id, self.name)  = self._first( identifier, ( (s['id'], s['name']) for s in self._surveysInfo(sq) if
                     (identifier == s['id'] if identifier.startswith('SV_') else regex.search( s['name'])) ) )
        self._responsesParameters = responsesParameters
        
    def responses(self):
        '''Answers the response for this survey as a dataframe'''
        if not hasattr(self, '_responses'):
            with self._q.fileFromPost('surveys/{}/export-responses'.format(self.id),
                                    {'format':'csv', **self._responsesParameters}) as f:
     
                # The response csv file format is:
                #     Column names, some predefined, plus questions in the form Q1, Q2_1 for subquestions, and 1_Q2 for repeated questions.
                #     The corresponding question titles
                #     The internal IDs for each question (in a json format)
                #     ... and then the responses.
                
                # To get the question answers, we skip the first two rows, so that Pandas assigns the right format to each column (esp dates)
                self._responses = pd.read_csv(f, skiprows=[1,2], parse_dates=['StartDate','EndDate'])
        return self._responses
        
    def setResponseSubset(self, responses):
        ''' Sets the responses considered by all the objects in this survey to be a subset of the total.
        responses: a DataFrame containg a subset of the rows returned by responses()'''
        self._responses = responses
        
    def question(self, identifier):
        '''Answers the question corresponding to identifier, which is either the question ID (e.g. Q1),
           or a regex string to match to the question text '''
        return Question(self, identifier)
        
    def _questionDefinitions(self):
        if not hasattr(self, '_questionDefs'):
            # Reverse the list, since more than one may have the same DataExportTag and we probably want the latest...
            self._questionDefs=self._q.getMultiple('survey-definitions/{}/questions'.format(self.id))[::-1]
        return self._questionDefs
        
    def questions(self):
        ''' Answers an array of Question objects.
        Each corresponds to the latest version of each of our questions that can have answers.'''
        
        questionNames=[qd['DataExportTag'] for qd in self._questionDefinitions() if qd.get('QuestionType') != 'DB']
        questionNames=list(OrderedDict.fromkeys(questionNames)) # Remove duplicates, keeping the last defined version of each.
        return [self.question(q) for q in questionNames[::-1]] # And reverse it back to the original order.




class SimpleQualtrics(object):
    ''' This class handles simple access to Qualtrics V3 APIs. It implements credentials,
    configuration handling, choice of API server, practical error handling, call timeouts,
    call logging, and Python-friendly decoding of Qualtrics response formats and protocols.
    
    There are many Qualtrics APIs in V3, but they tend to use standard calling and response patterns,
    so this library requires the caller to pass the API call strings and parameters;
    it provides Pythonic processing, chaining of multiple associated requests and error handling using exceptions.
    
    Try https://api.qualtrics.com/instructions/docs/Instructions/limits.md as a starting point for the documentation of the Qualtrics
    APIs.
    
    Example usage:
    
    # Import as modules:
    import SimpleQualtrics
    import pandas as pd
    
    # Use the following to log calls and errors to stderr:
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Initialise from configuration file:
    q=SimpleQualtrics.SimpleQualtrics(yaml='QualtricsCredentials.yaml')
    
    # Get a simple structure:
    myName = q.get('whoami')['firstName']
    
    # Get details of all mailing lists as a Pandas DataFrame:
    mailingLists=pd.DataFrame(q.getMultiple('mailinglists'))
    
    # Create a new mailing list, using our user ID as library ID:
    newListId=q.postCreate('mailinglists', {'name':'New List', 'libraryId': q.get('whoami')['userId']})
    
    # Delete that mailing list:
    q.delete('mailinglists/'+'newListId)
        
    If any Qualtrics requirements are not handled by the main functions here,
    use the *call* function, with similar semantics to *requests.request* , to incorporate credentials, errors and logging. E.g.
    
    responseContentFromDifferentCall = q.call('POST', 'different', json={'some': 'parameters'}).content
    
    The library uses standard Python logging, making a single INFO log entry for each outgoing call, and an ERROR
    log entry where exceptions are thrown.
    
    Credentials can be held in a yaml file. Example contents might be:
        token: 75STYGWg2nyQXTE46Ov7BDVSslFkt6TSkzxxxx # Your API token
        dataCenter: fra1 # Your data centre
        fileCreationTimeout: 60 # seconds.
        somethingElse:avalue # ...  any other relevant configuration you want to put in this file.
        
    See https://help-nv.qsrinternational.com/12/win/v12.1.96-d3ea61/Content/files/qualtrics-api-token.htm to find the tokens and IDs.
    
    Warning: If the Qualtrics server returns something undocumented, the library may throw an unhelpful exception like 'KeyError'.
    '''
    
    def __init__(self, **params):
        ''' Keyword parameters will be added to the configuration database
        
        yaml='filename.yaml' loads additional configuration from the given file.
        
        Required configuration parameters: token (the Qualtrics API token),
                                dataCenter (the Qualtrics center ID to use)
                                
        Optional configuration parameters: timeout, the timeout in seconds for calls, default 30;
                               fileCreationTimeout, the timeout in seconds for file creation, default same as the timeout above.
                               fileCreationPollIntervalMillis, the file creation polling interval in milliseconds, default 500.
                               '''
                               
        self.configDb=params
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
        ''' Answers the configuration entry for the given item, else a default if provided, else throws KeyError.'''
        return self.configDb[item] if default == None else self.configDb.get(item,default)
        
    # The basic Qualtrics CRUD API calls. We ignore metadata returned (except for error messages).
    
    def get(self, relPath):
        ''' Makes a GET request that answers a single structure as a Python dictionary.
        '''
        r=self.call('GET', relPath)
        return r.json()['result']
        
    def post(self, relPath, parameters):
        ''' Makes a POST request that returns a single structure as a Python dictionary.'''
        r=self.call('POST', relPath, json=parameters)
        return r.json()['result']
    
    def put(self, relPath, parameters):
        ''' Calls PUT for the given path and parameters'''
        self.call('PUT', relPath, json=parameters)
        
    def delete(self, relPath):
        ''' Calls DELETE for the given path'''
        self.call('DELETE', relPath)

    # A convenience wrapper around .post:
        
    def postCreate(self, relPath, parameters):
        ''' Does the specified post, answering the string id of the object created where this is the only entry in the results or
        where it contains one of the possibleIdFields fields, else None.
        '''
        possibleIdFields=['progressId']
        result=self.post( relPath, parameters)
        
        return next((result[key] for key in result)) if len(result) == 1 else next(
                               (result[field] for field in possibleIdFields if field in result), None)
        
    # More complex operations, involving multiple related calls:
    
    def getMultiple(self, relPath):
        ''' Makes a GET request that returns an array of structures, implementing paging if the API uses it.
        Answers an array of dictionaries,
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

    def fileFromPost(self, relPath, parameters, idField=None):
        '''Answers a filestream containing the result of the given request for a responses file.
        Supports both legacy and newer downloading of responses.
        
        Note that the filestream supports seek(), which allows it to be read more than once.
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
        ''' Does a generic call to url, which may be the full or the relative url,
        with the appropriate Qualtrics header, logging and timeout, answering a Requests Result object.
        
        Use json={someParameters} to pass parameters to a POST or PUT
        
        Raises (and logs) exceptions deriving from requests.RequestException in case of issues.'''
        
        url=url if url.startswith('https://') else self.baseUrl + url
        self.logger.info('{} {}{}'.format(action, url, (' with payload: ' + str(kwargs['json']) if 'json' in kwargs else '')))
        r=requests.request(action, url, **self.requestsParameters, **kwargs)
        try:
            if 400 <= r.status_code <= 500: # Qualtrics returns its error messages in the JSON:
                raise QualtricsError( r.json()['meta']['error']['errorMessage'], response=r)
            r.raise_for_status()
        except requests.RequestException as e:
            self.logger.error( repr(e) )
            raise
        return r

