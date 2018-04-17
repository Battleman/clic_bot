"""
Shows basic usage of the Sheets API. Prints values from a Google Spreadsheet.
"""
from apiclient.discovery import build
from httplib2 import Http
from oauth2client import client, file, tools
import json

SCOPES = 'https://sheets.googleapis.com/'
SPREADSHEET_ID = '1mQIR3h6MIV8cEbIVjgRlZtTZtxhYzZLhxVaEQQruQZY'
RANGE_NAME = 'Stock!A1:C6'

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
    
    result = serv.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                range=RANGE_NAME).execute()
    values = result.get('values', [])
    if not values:
        print('No data found.')
    else:
        return values
def appendValue(serv, vals):
    body = {
        "majorDimension": "ROWS",
        "values": [
            vals[0],vals[1],vals[2]
        ],
    }
    return serv.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range='Stock!A7:C7', insertDataOption='INSERT_ROWS', valueInputOption='RAW', body=body)
    # return success
