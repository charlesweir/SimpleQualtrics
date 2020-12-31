.. SimpleQualtrics documentation master file

Welcome to SimpleQualtrics |version|
====================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


Introduction
============

SimpleQualtrics is a stand-alone simple API to access the Qualtrics APIs directly,
handling all of the Qualtrics web-specific protocols in a robust manner and
answering data structures that are easy to process in Python.

Specifically, it implements separating credentials from code,
configuration handling, choice of API server, practical error handling, call timeouts,
call logging, and Python-friendly decoding of Qualtrics response formats and protocols.

Using SimpleQualtrics
=====================

There are many Qualtrics APIs in V3, but they use standard calling and response patterns.

So SimpleQualtrics provides full coverage of all the Qualtrics APIs
by requiring the caller to pass the API call strings and parameters.
It provides Pythonic processing, chaining of multiple associated requests and file-access requests,
logging, timeouts, and error handling using exceptions.

Example usage::

    # Import as modules:
    import SimpleQualtrics
    import pandas as pd

    # Include the following to log calls and errors to stderr:
    import logging
    logging.basicConfig(level=logging.INFO)

    # Initialise from configuration file:
    q=SimpleQualtrics.Session(yaml='QualtricsCredentials.yaml')

    # Get a simple structure:
    myName = q.get('whoami')['firstName']

    # Get details of all mailing lists as a Pandas DataFrame:
    mailingLists=pd.DataFrame(q.getMultiple('mailinglists'))

    # Create a new mailing list, using our user ID as library ID:
    newListId=q.postCreate('mailinglists', {'name':'New List', 'libraryId': q.get('whoami')['userId']})

    # Delete that mailing list:
    q.delete('mailinglists/'+newListId)

    # Get survey results:
    responsesDataFrame=pd.read_csv(q.fileFromPost('surveys/SV_999999999999999/export-responses',{'format':'csv'}))

Try https://api.qualtrics.com/instructions/docs/Instructions/limits.md as a starting point for the documentation of the Qualtrics
APIs.

If your Qualtrics requirements are not handled by the higher level functions (get, post, put, delete, etc.),
use the *call* function. It has similar semantics to `requests.request`,
but adds Qualtrics credentials, errors, timeouts and logging. E.g.::

    responseContentFromDifferentCall = q.call('POST', 'different', json={'some': 'parameters'}).content

The library uses standard Python logging, making a single INFO log entry for each outgoing call, and an ERROR
log entry where exceptions are thrown.


SimpleQualtrics Configuration
=============================

Credentials can be held in a yaml file. Example contents might be::

    token: 75STYGWg2nyQXTE46Ov7BDVSslFkt6TSkzxxxx # Your API token
    dataCenter: fra1 # Your data centre
    fileCreationTimeout: 60 # seconds.
    somethingElse:avalue # ...  any other relevant configuration that might be convenient to put in this file.

The required configuration parameters are:
     **token**
        the Qualtrics API token
     **dataCenter**
        the Qualtrics center ID to use)

Optional configuration parameters are:
     **timeout**
        the timeout in seconds for calls, default 30;
     **fileCreationTimeout**
        the timeout in seconds for file creation, default same as the timeout above.
     **fileCreationPollIntervalMillis**
        the file creation polling interval in milliseconds, default 500.

See https://help-nv.qsrinternational.com/12/win/v12.1.96-d3ea61/Content/files/qualtrics-api-token.htm to find the tokens.

Code Documentation
==================

.. automodule:: SimpleQualtrics

.. autoclass:: Session
   :members:
   
.. autoexception:: QualtricsError
    :show-inheritance:



