"""
Shows basic usage of the Sheets API. Prints values from a Google Spreadsheet.
"""
from __future__ import print_function
from apiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
SCOPES = 'https://sheets.googleapis.com/'
SPREADSHEET_ID = '1mQIR3h6MIV8cEbIVjgRlZtTZtxhYzZLhxVaEQQruQZY'
service = None

def init():
    """ Setup the Sheets API"""
    store = file.Storage('credentials.json')
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('client_secret.json', SCOPES)
        creds = tools.run_flow(flow, store)
    service = build('sheets', 'v4', http=creds.authorize(Http()), cache_discovery=False)
    return service
def getAllValues(serv):
    RANGE_NAME = 'Stock!A1:C6'
    result = serv.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                range=RANGE_NAME).execute()
    values = result.get('values', [])
    if not values:
        print('No data found.')
    else:
        return values