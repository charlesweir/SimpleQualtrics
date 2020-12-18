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
        qq=SimpleQualtrics.SimpleQualtrics(token='t', dataCenter='d')
        self.assertEqual(qq.config('token'),'t')
        self.assertEqual(qq.config('notPresent','u'),'u')
        with pytest.raises(KeyError):
            qq.config('notPresent')
            
    def test_incomplete_configuration(self):
        with pytest.raises(AssertionError):
            SimpleQualtrics.SimpleQualtrics(token='t')
            
    def test_parameters_from_yaml(self):
        with TemporaryDirectory() as tempDir: # NamedTemporaryFile is inconsistent across OSs
            filename=os.path.join(tempDir, 'config.yaml')
            with open(filename,'w') as f:
                f.write('token: t\ndataCenter: d\nextra: e')
            qq=SimpleQualtrics.SimpleQualtrics(yaml=filename)
            self.assertEqual(qq.config('extra'),'e')
        
    def test_missing_yaml(self):
        with pytest.raises(FileNotFoundError):
            SimpleQualtrics.SimpleQualtrics(yaml='nonExistentFile')

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
        self.q=SimpleQualtrics.SimpleQualtrics(token='t', dataCenter='d',
                    fileCreationPollIntervalMillis=0)
        SimpleQualtrics.Survey._ssInfo = None # Reset lazy loading of survey list.
          
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
        qq=SimpleQualtrics.SimpleQualtrics(token='t', dataCenter='d', fileCreationTimeout=0)
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
        
 
class TestSurveyQuestionsAndChoices(TestCase):
    def setUp(self):
        self.q=SimpleQualtrics.SimpleQualtrics(token='t', dataCenter='d',
            fileCreationPollIntervalMillis=0)
        SimpleQualtrics.Survey._ssInfo = None # Reset lazy loading of survey list.
        setupFileResponse("""StartDate,EndDate,Q1,Q2_1,Q2_2,Q3
            ignore,ignore,ignore,ignore,ignore,ignore            
            ignore,ignore,ignore,ignore,ignore,ignore
            2020-11-14 09:49:55,2020-11-14 09:51:17,First answer,3,4,1
            """, 'surveys/SV_SomeId/export-responses', {'format': 'csv', 'a':'a'} )
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/survey-definitions/SV_SomeId/questions',
                        json= { "result": { "elements": [
            {
                "QuestionDescription": "something",
                "DataExportTag": "Q1",
                "QuestionType": "TE",
            },
            { 'QuestionDescription': 'How important are each of the following?',
              'DataExportTag': 'Q2',
              "QuestionType": "Matrix",
              'Choices': {'33': {'Display': 'Always available'},
               '34': {'Display': 'Secure against malicious attackers'},},
              'RecodeValues': {'33': '4', '34': '3'},
              'ChoiceOrder': ['33', '34'],
              'Answers': {'33': {'Display': 'Extremely important'},
               '34': {'Display': 'Very important'},},
            },
            {   "QuestionDescription": "In which country do you currently reside?",
                "DataExportTag": "Q3",
                "QuestionType": "MC",
                "Choices": {"1": { "Display": "Afghanistan"},
                "2": {"Display": "Albania" },}
            },
            {               
                "QuestionDescription": "Logos",
                "DataExportTag": "Intro2",
                "QuestionType": "DB",
            },           
            ] }})
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/surveys',
                        json= { "result": { "elements": [
                              { "id": "SV_SomeId", "name": "The Survey Name", },
                            ],
                          },
                        })
        
    @responses.activate
    def test_survey_and_responses(self):         
        s=SimpleQualtrics.Survey(self.q, 'SV_SomeId', a='a')
        self.assertEqual(s.name, 'The Survey Name')
        with pytest.raises(SimpleQualtrics.QualtricsDataError) as excinfo:
            SimpleQualtrics.Survey(self.q, 'nonExistentId')
        excinfo.match('[Nn]ot found')

        df=s.responses()
        self.assertEqual(df.columns.values.tolist(), ['StartDate', 'EndDate', 'Q1', 'Q2_1', 'Q2_2', 'Q3'] )
        self.assertEqual(df.iloc[0]['Q1'],'First answer')
        self.assertRegex(str(type(df.iloc[0]['StartDate'])),'Timestamp') # It's converted them to times.

    @responses.activate
    def test_questions(self):         
        s=SimpleQualtrics.Survey(self.q, 'SV_SomeId', a='a')
        self.assertEqual([q.id for q in s.questions()], ['Q1', 'Q2', 'Q3'] )
        self.assertEqual(s.question('Q1').id, 'Q1')
        self.assertEqual(s.question('Q1').name, 'something')
        self.assertEqual(s.question('Q2').choice(4).name, 'Extremely important')
        self.assertEqual(s.question('Q3').choice(2).name, 'Albania')
        with pytest.raises(SimpleQualtrics.QualtricsDataError):
            s.question('Q999')
            
    @responses.activate
    def test_sub_questions(self):         
        s=SimpleQualtrics.Survey(self.q, 'SV_SomeId', a='a')        
        q2=s.question('How important')
        self.assertEqual(q2.id, 'Q2')
        self.assertEqual(q2.subQuestion(1).name, 'Always available')
        self.assertEqual(q2.subQuestion('available').id, 1)
        self.assertEqual([q.id for q in q2.subQuestions()], [1, 2])
        with pytest.raises(SimpleQualtrics.QualtricsDataError):
            q2.subQuestion('non existent subquestion')
        
        self.assertEqual(q2.choice('[Ee]xtremely').id, 4)
        self.assertEqual(q2.choice(3).name, 'Very important')
        self.assertEqual([c.id for c in q2.choices()], [3, 4])
        with pytest.raises(SimpleQualtrics.QualtricsDataError):
            q2.choice(999)
       
        with pytest.raises(SimpleQualtrics.QualtricsDataError):
            q2.responses() 
        self.assertEqual(q2.subQuestion(1).responses().iloc[0], 3) 
        self.assertEqual(s.question('Q1').responses().iloc[0], 'First answer')
        self.assertEqual(s.question('Q3').responses().iloc[0], 1)
    
    @responses.activate
    def test_repr(self):
        s=SimpleQualtrics.Survey(self.q, 'SV_SomeId')        
        self.assertRegex(repr(s.question('Q1')), 'Question Q1: something')
        self.assertRegex(repr(s.question('Q2').choice(4)), 'Choice 4: Extremely important')
        self.assertRegex(repr(s.question('Q2').subQuestion('available')), 'SubQuestion 1: Always available')
        self.assertRegex(repr(s), 'Survey SV_SomeId: The Survey Name')
    
    @responses.activate
    def test_cache_list(self):
        # Must cache the survey list:
        SimpleQualtrics.Survey(self.q, 'SV_SomeId')
        SimpleQualtrics.Survey(self.q, 'SV_SomeId')
        responses.assert_call_count('https://d.qualtrics.com/API/v3/surveys', 1)

class TestMiscStuff(TestCase):
    def setUp(self):
        self.q=SimpleQualtrics.SimpleQualtrics(token='t', dataCenter='d',
            fileCreationPollIntervalMillis=0)
        SimpleQualtrics.Survey._ssInfo = None # Reset lazy loading of survey list.
        
    @responses.activate
    def test_survey_from_name(self):  
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/surveys',
                        json= { "result": { "elements": [
                              { "id": "SV_1", "name": "First Survey", },
                              { "id": "SV_2", "name": "Second survey", },
                            ],
                            "nextPage": None
                          },
                        })
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/survey-definitions/SV_2/metadata',
                        json= { "result": {
                            "SurveyID": "SV_2",
                            "SurveyName": "Second survey" }
                        })
        s=SimpleQualtrics.Survey(self.q, '[Ss]econd' )
        self.assertEqual(s.id, 'SV_2')
        self.assertEqual(s.name, "Second survey")
        self.assertEqual( [s.id for s in SimpleQualtrics.Survey.all(self.q)], ['SV_1','SV_2'])
        
        
    @responses.activate
    def test_user_id(self):
        responses.add(responses.GET, 'https://d.qualtrics.com/API/v3/whoami',
                        json={ "result": {'brandId': 'lancasteruni', 'userId': 'UR_me', 
                                         'firstName': 'a', 'lastName': 'b'} })
        user=SimpleQualtrics.CurrentUser(self.q)
        self.assertEqual( user.id, 'UR_me')
        self.assertEqual( user.id, 'UR_me')
        responses.assert_call_count('https://d.qualtrics.com/API/v3/whoami', 1) # it caches the result.
        
        
if 'ipykernel' in sys.modules:
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
elif __name__ == '__main__':
        unittest.main()

