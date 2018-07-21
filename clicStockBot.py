"""
ClicBot.py
Author: Olivier Cloux
This module allows our student association (the Clic) to manage its stock, and 
more
"""
import itertools
# import json
import logging
# import subprocess
import sys
import time
from datetime import datetime, timedelta
from os.path import isfile
from pprint import pprint

import schedule
import telegram
import yaml
from apiclient.discovery import build
from dateutil.parser import parse
from httplib2 import Http
from oauth2client import client, file, tools
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater
from telegram.utils.request import Request

# ########
# Load the config file
# Set the Botname / Token
# ##########
config_file = 'config.yaml'
if isfile(config_file):
    with open(config_file) as fp:
        config = yaml.load(fp)
else:
    pprint("config.yaml file does not exists. Please make from "
           "config.sample.yaml file")
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
SUBSCRIBED_EXPIRY_FILENAME = config['SUBSCRIBED_EXPIRY_FILENAME']

commands = {'list': 'List all items in stock',
            'help': 'This command help :)',
            # 'quit': 'stop the bot. For everyone. Forever.',
            'identify': 'Let the owner know your TG ID.'
            ' Only useful for admins.',
            'new': 'Add an item to the stock',
            'search': 'Enter a string to search for in the stock',
            'update': 'Update an existing entry in the stock',
            'subscribe': "Subscribe to the expiry messaging list. "
            "Every day at 12h00, you'll receive a message about"
            " the next and currently  expired items"
            }


#####################
# Configure Logging

FORMAT = '%(asctime)s -- %(levelname)s -- %(module)s %(lineno)d -- %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
logger = logging.getLogger('root')
logger.info("Running %s", sys.argv[0])


############################
# Telegram functions

def tg_start(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text="I'm a bot, please talk to me!")


def tg_quit(bot, update):
    if update.message.chat_id != OWNER_ID:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Sorry, you can't perform this task. You're not "
                         "an admin.")
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


def pprint_tg(bot, chat_id,
              l,
              header="The following items are in stock:\n",
              columns=config['COLS_NAMES']):
    line = "{},\t\t"*(NUM_COLS-1) + "{}"
    content = "\n\n".join([line.format(elem[NUM_COL_NAME],
                                       elem[NUM_COL_QTY],
                                       elem[NUM_COL_UNIT],
                                       elem[NUM_COL_EXPIRY]) for elem in l])
    # content+="\n\n"+"\n\n".join([)
    s = header + content
    bot.send_message(chat_id=chat_id,
                     text="The following articles are in stock:\n{}".format(s))


def tg_unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id,
                     text="Sorry, I didn't understand that command.")


def tg_helper(bot, update):
    helpHeader = "Hi! This is the help message for ClicStock_Bot. \
    Here are the various commands you can use: \n\n"
    helpBody = "\n".join(["{}\t\t{}".format(x, commands[x]) for x in commands])
    bot.send_message(chat_id=update.message.chat_id, text=helpHeader+helpBody)


def tg_echo(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=update.message.text)


def tg_addItem(bot, update, args):
    newObj = parseListCommas(args)
    if len(newObj) < MIN_NUM_COLS or len(newObj) > NUM_COLS:
        message = "You need to specify the object, quantity, unit and \
        optionally the expiry date (commas separated), no more"
        bot.send_message(chat_id=update.message.chat_id, text=message)
        return

    # at this point, we have between MIN_NUM_COLS and NUM_COLS columns
    try:  # always check the quantity
        newObj[NUM_COL_QTY] = float(newObj[NUM_COL_QTY])
        assert newObj[NUM_COL_QTY] >= 0
    except (ValueError, AssertionError):
        message = "Your second item (quantity) could not be understood \
        as a positive number. Please check."
        logger.warning('Chat id %d tried to add quantity %s',
                       update.message.chat_id, newObj[NUM_COL_QTY])
        bot.send_message(chat_id=update.message.chat_id, text=message)
        return

    if len(newObj) == NUM_COLS:
        # if date is specified, try to parse
        try:
            newObj[NUM_COL_EXPIRY] = parse(newObj[NUM_COL_EXPIRY])
        except ValueError:
            message = "Your last item (expiration date) could not \
            be understood as a date. Please check."
            logger.warning('Chat id %s tried to add expire date %s',
                           update.message.chat_id, newObj[NUM_COL_EXPIRY])
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
    user_id = update.message.chat_id
    if len(args) > 0:
        print("User with ID {} just identified himself as {}".format(
            user_id, args[0]))
    else:
        logger.info("User with ID %s just identified himself anonymously",
                    user_id)
    return user_id


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
                         text="You did not specify enough arguments. Specify "
                         "at least Item and Quantity (comma separated)")
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
    index = [i for i, v in enumerate(values[0]) if v.lower() == obj]
    if(len(index) == 0):
        bot.send_message(chat_id=update.message.chat_id,
                         text=config['ERROR_UPDATE_404'].format(obj))
        return
    elif(len(index > 1)):
        header = config['ERROR_UPDATE_TOO_MANY_MATCH']
        names = index  # TODO keep only names
        pprint_tg(bot, update.message.chat_id, names, header)
        return
    objPos = index[0][0]  # TODO Check this is correct
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


def tg_subscribe_expiry(bot, update):
    with open(SUBSCRIBED_EXPIRY_FILENAME, mode='r+') as f:
        for i in f:
            if i.strip() == str(update.message.chat_id):
                message = "Sorry, you are already subscribed to this list."
                bot.send_message(chat_id=update.message.chat_id,
                                 text=message)
                return
        # if we did not return, we are at the end of the file, we can append
        ret = f.write(str(update.message.chat_id)+"\n")
        if ret > 0:
            message = "You subscribes to this list! Congratulations"
        else:
            message = "Something wrong happened... contact an admin"
        bot.send_message(chat_id=update.message.chat_id,
                         text=message)


def tg_unsubscribe_expiry(bot, update):
    lines = []
    with open(SUBSCRIBED_EXPIRY_FILENAME, mode="r") as f:
        found = False
        for i in f:
            if not str(update.message.chat_id) in i:
                lines.append(i)
            else:
                found = True
    if found:
        with open(SUBSCRIBED_EXPIRY_FILENAME, mode="w") as f:
            f.writelines(lines)
        message = "You were correctly unsubscribed."
    else:
        message = "You are not currently subscribed. \
        Use /subscribe to subscribe."

    bot.send_message(chat_id=update.message.chat_id, text=message)


def check_expiry(bot, update=None):

    today = datetime.today()
    vals = gs_getAllValues()[1:]
    # keeps values in next 7 days
    sensible = [v for v in vals if ('NA' not in v[NUM_COL_EXPIRY]) and
                (parse(v[NUM_COL_EXPIRY]) - timedelta(days=7) < today)]
    stillGood = [v for v in sensible if parse(v[NUM_COL_EXPIRY]) >= today]
    expired = [v for v in sensible if parse(v[NUM_COL_EXPIRY]) < today]

    line = "-->"+"{},\t\t"*(NUM_COLS-1) + "{}"
    message = ""
    if len(stillGood) == 0:
        message += "No good will be expired in the next 7 days\n###########\n"
    else:
        message += "The following good(s) will be expired in the next week:\n"
        message += "\n".join([line.format(elem[NUM_COL_NAME],
                                          elem[NUM_COL_QTY],
                                          elem[NUM_COL_UNIT],
                                          elem[NUM_COL_EXPIRY])
                              for elem in stillGood])
        message += "\n###########\n"
    if len(expired) == 0:
        message += "No good is currently expired\n###########\n"
    else:
        message += "The following good(s) already expired. SHAME !:\n"
        message += "\n".join([line.format(elem[NUM_COL_NAME],
                                          elem[NUM_COL_QTY],
                                          elem[NUM_COL_UNIT],
                                          elem[NUM_COL_EXPIRY])
                              for elem in expired])
        message += "\n###########\n"
    if update is None:
        with open(SUBSCRIBED_EXPIRY_FILENAME, mode='r') as f:
            for user_id in f:
                bot.send_message(chat_id=user_id, text=message)
    else:
        bot.send_message(chat_id=update.message.chat_id, text=message)
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
    sheet_range = "Stock!A2:C2"
    response = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        sheet_range=sheet_range,
        body=resource,
        valueInputOption="USER_ENTERED"
    ).execute()
    return response


def gs_getService():
    """ Setup the Sheets API"""
    store = file.Storage('credentials.json')
    credentials = store.get()
    if not credentials or credentials.invalid:
        print("Credentials invalid, renewing")
        flow = client.flow_from_clientsecrets('client_secret.json', SCOPE)
        credentials = tools.run_flow(flow, store)
    service = build('sheets', 'v4', http=credentials.authorize(
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
    result = gs_getService().spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
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

# schedule.every().day.at("12:00").do(check_expiry, clic_bot)
# schedule.every(1).minutes.do(check_expiry, clicBot)


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
dispatcher.add_handler(CommandHandler(
    'subscribe', tg_subscribe_expiry))
dispatcher.add_handler(CommandHandler(
    'unsub', tg_unsubscribe_expiry))

dispatcher.add_handler(CommandHandler(
    'test', check_expiry))

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
