#!/home/battleman/Programs/anaconda3/bin/python
import itertools
import json
import logging
import sys
from os.path import isfile
from pprint import pprint
from dateutil.parser import parse
import telegram
import yaml
import schedule
import time
from apiclient.discovery import build
from httplib2 import Http
from oauth2client import client, file, tools
from telegram.utils.request import Request
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

"""
#	Load the config file
#	Set the Botname / Token
"""
config_file = 'config.yaml'
if isfile(config_file):
    with open(config_file) as fp:
        config = yaml.load(fp)
else:
    pprint('config.yaml file does not exists. Please make from config.sample.yaml file')
    sys.exit()

#####################
# Constants

TOKEN = config['CLICSTOCK_TOKEN']
BOTNAME = config['CLICSTOCK_BOTNAME']
SPREADSHEET_ID = config['CLIC_SHEETID']
SCOPE = config['CLIC_SHEET_SCOPE']
OWNER_ID = config['OWNER_ID']
COL_START = config['COL_START']
COL_END = config['COL_END']
ROW_START = config['ROW_START']
VALUES_RANGE_START = '{}!{}{}:{}{}'.format(
    config['SHEET_NAME'], COL_START, ROW_START, COL_END, ROW_START)
VALUES_RANGE_COLS = '{}!{}:{}'.format(
    config['SHEET_NAME'], COL_START, COL_END)
MIN_NUM_COLS = config['MANDATORY_COLS']
MIN_NUM_COLS_UPDATE = config['MANDATORY_COLS_UPDATE']
NUM_COLS = config['NUM_COLS']

NUM_COL_NAME = config['NUM_COL_NAME']
NUM_COL_QTY = config['NUM_COL_QTY']
NUM_COL_UNIT = config['NUM_COL_UNIT']
NUM_COL_EXPIRY = config['NUM_COL_EXPIRY']

commands = {'list': 'List all items in stock',
            'help': 'This command help :)',
            # 'quit': 'stop the bot. For everyone. Forever.',
            'identify': 'Let the owner know your TG ID. Only useful for admins.',
            'new': 'Add an item to the stock',
            'search': 'Enter a string to search for in the stock',
            'update': 'Update an existing entry in the stock'
            }


#####################
# Configure Logging

FORMAT = '%(asctime)s -- %(levelname)s -- %(module)s %(lineno)d -- %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
logger = logging.getLogger('root')
logger.info("Running "+sys.argv[0])


############################
# Telegram functions

def tg_start(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text="I'm a bot, please talk to me!")

def tg_quit(bot, update):
    if update.message.chat_id != OWNER_ID:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Sorry, you can't perform this task. You're not an admin.")
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Thanks for talking with me. By by !")
        updater.stop()
        sys.exit()

def tg_listItems(bot, update):
    values = gs_getAllValues()
    # print("[LIST] raw values are:", values)
    header = values[0]
    l = values[1:]
    pprint_tg(bot, update, l, header)

def pprint_tg(bot, update, l, header=""):
    titre = "Object, Quantity, Unit, Expiry Date\n"
    # content = "\n\n".join(["{}\t\t{}\t\t{}".format(v[0], v[1], v[2]) if len(v) == 3
                        #    else "{}\t\t{}".format(v[0], v[1]) for v in l[1:] if len(v) > 1])
    line = "{},\t\t"*(NUM_COLS-1) + "{}"
    content = "\n\n".join([line.format(elem[NUM_COL_NAME], elem[NUM_COL_QTY], elem[NUM_COL_UNIT], elem[NUM_COL_EXPIRY]) for elem in l])                   
    # content+="\n\n"+"\n\n".join([)
    s = titre + content
    bot.send_message(chat_id=update.message.chat_id,
                     text="The following articles are in stock:\n{}".format(s))

def tg_unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text="Sorry, I didn't understand that command.")

def tg_helper(bot, update):
    helpHeader = "Hi! This is the help message for ClicStock_Bot. Here are the various commands you can use:\n\n"
    helpBody = "\n".join(["{}\t\t{}".format(x, commands[x]) for x in commands])
    bot.send_message(chat_id=update.message.chat_id, text=helpHeader+helpBody)

def tg_echo(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=update.message.text)

def tg_addItem(bot, update, args):
    newObj = parseListCommas(args)
    if len(newObj) < MIN_NUM_COLS or len(newObj) > NUM_COLS:
        message = "You need to specify the object, quantity, unit and optionally the expiry date (commas separated), no more"
        bot.send_message(chat_id=update.message.chat_id, text=message)
        return

    # at this point, we have between MIN_NUM_COLS and NUM_COLS columns
    try:  # always check the quantity
        newObj[NUM_COL_QTY] = float(newObj[NUM_COL_QTY])
        assert newObj[NUM_COL_QTY] >= 0
    except (ValueError, AssertionError):
        message = "Your second item (quantity) could not be understood as a positive number. Please check."
        logger.warn('Chat id {} tried to add quantity {}'.format(
            update.message.chat_id, newObj[NUM_COL_QTY]))
        bot.send_message(chat_id=update.message.chat_id, text=message)
        return

    if len(newObj) == NUM_COLS:
        # if date is specified, try to parse
        try:
            newObj[NUM_COL_EXPIRY] = parse(newObj[NUM_COL_EXPIRY])
        except ValueError:
            message = "Your last item (expiration date) could not be understood as a date. Please check."
            logger.warn('Chat id {} tried to add expire date {}'.format(
                update.message.chat_id, newObj[NUM_COL_EXPIRY]))
            bot.send_message(chat_id=update.message.chat_id, text=message)
            return
    else:  # if no date specified, add NA
        newObj += ['NA']

    items = gs_getValuesFromResponse(gs_getValuesResponse()).values()

    if newObj[NUM_COL_NAME].lower() in items:
        message = "This item already exists in the stock"
    else:
        success = gs_appendValue(newObj)
        if(success['updates']['updatedCells'] == len(newObj)):
            message = "Successfully added this item"
        else:
            message = "Failed to add... please refer to an admin"
    bot.send_message(chat_id=update.message.chat_id, text=message)

def tg_getChatID(bot, update, args):
    id = update.message.chat_id
    if len(args) > 0:
        print("User with ID {} just identified himself as {}".format(
            id, args[0]))
    else:
        print("User with ID {} just identified himself anonymously".format(id))
    return id

def tg_searchItem(bot, update, args):
    args = parseListCommas(args)
    if len(args) > 1:
        message = "You can't search with more that 1 term"
        bot.send_message(chat_id=update.message.chat_id, text=message)
        return
    word = args[0]

    items = gs_getAllValues()
    result = []
    for i in items[1:]:
        if i[NUM_COL_NAME].lower().find(word.lower()) >= 0:
            result += [i]
    
    pprint_tg(bot, update, result)

def tg_updateValue(bot, update, args):
    # Arguments parsing
    # Required positions :[name (str), +/- quantity (int), {comment}]
    parsed = parseListCommas(args)
    if len(parsed) < MIN_NUM_COLS_UPDATE:
        bot.send_message(chat_id=update.message.chat_id,
                         text="You did not specify enough arguments. Specify at least Item and Quantity (comma separated)")
        return

    obj = parsed[0].lower()

    # interpret quantity as relative or absolute
    try:
        quantity = int(parsed[1])
    except ValueError:
        bot.send_message(chat_id=update.message.chat_id,
                         text=config['ERROR_UPDATE_VALUE'])
        return
    if parsed[1][0] == '+' or parsed[1][0] == '-':
        relative = True
    else:
        relative = False

    # find index of value to update
    rawValues = gs_getAllValues()
    values = list(itertools.zip_longest(*rawValues))
    print(values)
    index = (i for i, v in enumerate(values[0]) if v.lower() == obj)
    try:
        objPos = next(index)
    except StopIteration:
        bot.send_message(chat_id=update.message.chat_id,
                         text=config['ERROR_UPDATE_404'].format(obj))
        return

    # find new value according to relativity
    newVal = quantity
    if relative:
        newVal += int(values[1][objPos])
    # update
    response = gs_UpdateValue(objPos+1, newVal)
    if response['responses'][0]['updatedCells'] == 1:
        bot.send_message(chat_id=update.message.chat_id,
                         text=config['UPDATE_OK'])
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text=config['UPDATE_NOT_OK'])

def check_expiry():
    logger.info("The cron works !")

########################
#   Google Sheet functions
def gs_appendValue(value):
    service = gs_getService()
    print(len(value))
    print(value)
    if len(value) <= 3:
        value += ['NA']
    resource = {
        "majorDimension": "ROWS",
        "values": [
            value
        ]
    }
    range = "Stock!A2:C2"
    response = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=range,
        body=resource,
        valueInputOption="USER_ENTERED"
    ).execute()
    return response


def gs_getService():
    """ Setup the Sheets API"""
    store = file.Storage('credentials.json')
    creds = store.get()
    if not creds or creds.invalid:
        print("Credentials invalid, renewing")
        flow = client.flow_from_clientsecrets('client_secret.json', SCOPE)
        creds = tools.run_flow(flow, store)
    service = build('sheets', 'v4', http=creds.authorize(
        Http()), cache_discovery=False)
    return service


def gs_getValuesResponse():
    service = gs_getService()
    body = {
        "majorDimension": "ROWS",
        "dataFilters": [
            {
                "gridRange": {
                    "endColumnIndex": 1,
                    "sheetId": 0,
                    "startColumnIndex": 0,
                    "startRowIndex": 1
                }
            }
        ],
        "valueRenderOption": "UNFORMATTED_VALUE"
    }
    response = service.spreadsheets().values().batchGetByDataFilter(
        spreadsheetId=SPREADSHEET_ID,
        body=body
    ).execute()
    # print("Response to the getValueRange is\n", response)
    return response


def gs_getValuesFromResponse(response):
    values = [x[0].lower() for x in response['valueRanges'][0]
              ['valueRange']['values'] if len(x) > 0]
    withPos = dict(enumerate(values))
    # print(withPos)
    return withPos


def gs_getAllValues():
    result = gs_getService().spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                         range=VALUES_RANGE_COLS).execute()
    values = result.get('values', [])
    if not values:
        print('No data found.')
    else:
        return values


def gs_UpdateValue(row, value, comment=False):
    service = gs_getService()
    # if comment:
    #     val, com = value
    body = {
        "data": [
            {
                "majorDimension": "ROWS",
                "range": "B"+str(row),
                "values": [
                    [
                        value
                    ]
                ]
            }
        ],
        "includeValuesInResponse": True,
        "valueInputOption": "RAW"
    }
    response = service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body=body).execute()
    print(response)
    return(response)


##########################
# Cron for expiry dates

###########################
# Begin bot

request = Request(con_pool_size=8)
clicBot = telegram.Bot(token=TOKEN, request=request)
updater = Updater(bot=clicBot)

# schedule.every().day.at("12:00").do(check_expiry())
schedule.every(1).minutes.do(check_expiry)


dispatcher = updater.dispatcher


dispatcher.add_handler(CommandHandler(
    'quit', tg_quit))
dispatcher.add_handler(CommandHandler(
    'list', tg_listItems))
dispatcher.add_handler(CommandHandler(
    'update', tg_updateValue, pass_args=True))
dispatcher.add_handler(CommandHandler(
    'start', tg_start))
dispatcher.add_handler(CommandHandler(
    'help', tg_helper))
dispatcher.add_handler(CommandHandler(
    'new', tg_addItem, pass_args=True))
dispatcher.add_handler(CommandHandler(
    'identify', tg_getChatID, pass_args=True))
dispatcher.add_handler(CommandHandler(
    'search', tg_searchItem, pass_args=True))

# dispatcher.add_handler(MessageHandler(Filters.text, tg_echo))
dispatcher.add_handler(MessageHandler(Filters.command, tg_unknown))

logger.info("Starting polling")
updater.start_polling()

######################
#       UTILS

def parseListCommas(l):
    """
        Takes a list of strings, and separate it in strings following commas

        Example: parseListCommas(['this','is,','a','list,','of','strings'])
            >>> ['this is', 'a list', 'of strings']
    """
    if type(l) != list:
        return []
    placeholder = ['']
    for s in l:
        if ',' in s:
            s = s.replace(',', '')
            placeholder[-1] += s
            placeholder.append('')
        else:
            placeholder[-1] += s + " "
        # print(placeholder)
    placeholder[-1] = placeholder[-1][:-1]  # remove trailing space
    return placeholder


while 1:
    schedule.run_pending()
    time.sleep(30)

