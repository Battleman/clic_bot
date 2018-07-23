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
import yaml
from uuid import uuid4
from telegram.utils.helpers import escape_markdown
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup,\
    InlineQueryResultArticle, InlineQueryResult, InputTextMessageContent,\
    ParseMode
from telegram.ext import CommandHandler, Filters, MessageHandler,\
    Updater, CallbackQueryHandler, InlineQueryHandler
from telegram.utils.request import Request
from apiclient.discovery import build
from dateutil.parser import parse
from httplib2 import Http
from oauth2client import client, file, tools

# ########
# Load the config file
# Set the Botname / Token
# ##########
CONFIG_FILE = 'config.yaml'
if isfile(CONFIG_FILE):
    with open(CONFIG_FILE) as fp:
        CONFIG = yaml.load(fp)
else:
    pprint("config.yaml file does not exists. Please make from "
           "config.sample.yaml file")
    sys.exit()

#####################
# Constants

TOKEN = CONFIG['CLICSTOCK_TOKEN']
BOTNAME = CONFIG['CLICSTOCK_BOTNAME']
SPREADSHEET_ID = CONFIG['CLIC_SHEETID']
SCOPE = CONFIG['CLIC_SHEET_SCOPE']
OWNER_ID = CONFIG['OWNER_ID']
COL_START = CONFIG['COL_START']
COL_END = CONFIG['COL_END']
ROW_START = CONFIG['ROW_START']
VALUES_RANGE_START = '{}!{}{}:{}{}'.format(
    CONFIG['SHEET_NAME'], COL_START, ROW_START, COL_END, ROW_START)
VALUES_RANGE_COLS = '{}!{}:{}'.format(
    CONFIG['SHEET_NAME'], COL_START, COL_END)
MIN_NUM_COLS = CONFIG['MANDATORY_COLS']
MIN_NUM_COLS_UPDATE = CONFIG['MANDATORY_COLS_UPDATE']
NUM_COLS = CONFIG['NUM_COLS']

NUM_COL_NAME = CONFIG['NUM_COL_NAME']
NUM_COL_QTY = CONFIG['NUM_COL_QTY']
NUM_COL_UNIT = CONFIG['NUM_COL_UNIT']
NUM_COL_EXPIRY = CONFIG['NUM_COL_EXPIRY']
SUBSCRIBED_EXPIRY_FILENAME = CONFIG['SUBSCRIBED_EXPIRY_FILENAME']

COMMANDS = {'list': 'List all items in stock',
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
logging.basicConfig(level=logging.DEBUG, format=FORMAT)
LOGGER = logging.getLogger('root')
LOGGER.info("Running %s", sys.argv[0])


############################
# Telegram functions

def tg_start(bot, update):
    """
    TELEGRAM FUNCTION
    Mandatory bot starting function
    """
    update.message.reply_text('Hi!')


def tg_quit(bot, update):
    """
    TELEGRAM FUNCTION
    Stop the bot. For admin only.
    """
    if update.message.chat_id != OWNER_ID:
        update.message.reply_text("Sorry, you can't perform this task. "
                                  "You're not an admin.")
    else:
        update.message.reply_text("Thanks for talking with me. By by !")
        UPDATER.stop()
        sys.exit()


def tg_list_items(bot, update):
    """
    TELEGRAM FUNCTION
    List all items in the stock
    """
    values = gs_get_all_values()
    columns = values[0]
    items = values[1:]
    pprint_tg(update, items, columns=columns)


def pprint_tg(update,
              items_list,
              header="The following items are in stock:\n",
              columns=CONFIG['COLS_NAMES']):
    """
    Send a message formatted nicely
    """
    line = "{},\t\t"*(NUM_COLS-1) + "{}"
    content = "\n\n".join([line.format(elem[NUM_COL_NAME],
                                       elem[NUM_COL_QTY],
                                       elem[NUM_COL_UNIT],
                                       elem[NUM_COL_EXPIRY])
                           for elem in items_list])
    cols = line.format(*columns)
    update.message.reply_text(header+cols+"\n"+content)


def tg_unknown(bot, update):
    """
    TELEGRAM FUNCTION
    Reaction when the command is unknown
    """
    update.message.reply_text("Sorry, I didn't understand that command.")


def tg_helper(bot, update):
    """
    TELEGRAM FUNCTION
    Help the user
    """
    help_header = "Hi! This is the help message for ClicStock_Bot. \
    Here are the various commands you can use: \n\n"
    help_body = "\n".join(["{}\t\t{}".format(x, COMMANDS[x])
                           for x in COMMANDS])
    update.message.reply_text(help_header+help_body)


def tg_add_item(bot, update, args):
    """
    TELEGRAM FUNCTION
    Add an item to the stock
    """
    new_obj = parse_list_commas(args)
    if len(new_obj) < MIN_NUM_COLS or len(new_obj) > NUM_COLS:
        message = "You need to specify the object, quantity, unit and " +
        "optionally the expiry date (commas separated), no more"
        update.message.reply_text(message)
        return

    # at this point, we have between MIN_NUM_COLS and NUM_COLS columns
    try:  # always check the quantity
        new_obj[NUM_COL_QTY] = float(new_obj[NUM_COL_QTY])
        assert new_obj[NUM_COL_QTY] >= 0
    except (ValueError, AssertionError):
        message = "Your second item (quantity) could not be understood \
        as a positive number. Please check."
        LOGGER.warning('Chat id %d tried to add quantity %s',
                       update.message.chat_id, new_obj[NUM_COL_QTY])
        update.message.reply_text(message)
        return

    if len(new_obj) == NUM_COLS:
        # if date is specified, try to parse
        try:
            new_obj[NUM_COL_EXPIRY] = parse(new_obj[NUM_COL_EXPIRY])
        except ValueError:
            message = "Your last item (expiration date) could not \
            be understood as a date. Please check."
            LOGGER.warning('Chat id %s tried to add expire date %s',
                           update.message.chat_id, new_obj[NUM_COL_EXPIRY])
            update.message.reply_text(message)
            return
    else:  # if no date specified, add NA
        new_obj += ['NA']

    items = gs_get_values_from_response(gs_get_values_response()).values()

    if new_obj[NUM_COL_NAME].lower() in items:
        message = "This item already exists in the stock"
    else:
        success = gs_append_value(new_obj)
        if success['updates']['updatedCells'] == len(new_obj):
            message = "Successfully added this item"
        else:
            message = "Failed to add... please refer to an admin"
    update.message.reply_text(message)


def tg_get_chat_id(bot, update, args):
    """
    TELEGRAM FUNCTION
    Let a user be known to the admin
    """
    user_id = update.message.chat_id
    if args:
        LOGGER.info("User with ID %d just identified himself as %s",
                    user_id, args[0])
    else:
        LOGGER.info("User with ID %s just identified himself anonymously",
                    user_id)
    return user_id


def tg_search_item(bot, update, args):
    """
    TELEGRAM FUNCTION
    Search an item in the stock
    """
    args = parse_list_commas(args)
    if len(args) > 1:
        message = "You can't search with more that 1 term"
        update.message.reply_text(message)
        return
    word = args[0]

    items = gs_get_all_values()
    result = []
    for i in items[1:]:
        if i[NUM_COL_NAME].lower().find(word.lower()) >= 0:
            result += [i]

    pprint_tg(bot, update, result)


def tg_update_value(bot, update, args):
    """
    TELEGRAM FUNCTION
    Update an item in the stock (e.g. its quantity in stock)
    """
    # Arguments parsing
    # Required positions :[name (str), +/- quantity (int), {comment}]
    parsed = parse_list_commas(args)
    if len(parsed) < MIN_NUM_COLS_UPDATE:
        update.message.reply_text("You did not specify enough arguments."
                                  "Specify at least Item and Quantity "
                                  "(comma separated)")
        return

    obj = parsed[0].lower()

    # interpret quantity as relative or absolute
    try:
        quantity = int(parsed[1])
    except ValueError:
        update.message.reply_text(CONFIG['ERROR_UPDATE_VALUE'])
        return
    relative = False
    if parsed[1][0] == '+' or parsed[1][0] == '-':
        relative = True

    # find index of value to update
    raw_values = gs_get_all_values()
    values = list(itertools.zip_longest(*raw_values))
    print(values)
    index = [i for i, v in enumerate(values[0]) if v.lower() == obj]
    if not index:
        update.message.reply_text(CONFIG['ERROR_UPDATE_404'].format(obj))
        return
    elif len(index) > 1:
        header = CONFIG['ERROR_UPDATE_TOO_MANY_MATCH']
        names = index  # TODO keep only names
        pprint_tg(bot, update.message.chat_id, names, header)
        return
    obj_pos = index[0][0]  # TODO Check this is correct
    # find new value according to relativity
    new_val = quantity
    if relative:
        new_val += int(values[1][obj_pos])
    # update
    response = gs_update_value(obj_pos+1, new_val)
    if response['responses'][0]['updatedCells'] == 1:
        update.message.reply_text(CONFIG['UPDATE_OK'])
    else:
        update.message.reply_text(CONFIG['UPDATE_NOT_OK'])


def tg_subscribe_expiry(bot, update):
    """
    TELEGRAM FUNCTION
    Subscribe a user to the expiry alerts
    """
    with open(SUBSCRIBED_EXPIRY_FILENAME, mode='r+') as subscribers:
        for i in subscribers:
            if i.strip() == str(update.message.chat_id):
                message = "Sorry, you are already subscribed to this list."
                update.message.reply_text(message)
                return
        # if we did not return, we are at the end of the file, we can append
        ret = subscribers.write(str(update.message.chat_id)+"\n")
        if ret > 0:
            message = "You subscribes to this list! Congratulations"
        else:
            message = "Something wrong happened... contact an admin"
            update.message.reply_text(message)


def tg_unsubscribe_expiry(bot, update):
    """
    TELEGRAM FUNCTION
    Unsubscribe a user to the expiry alerts
    """
    lines = []
    with open(SUBSCRIBED_EXPIRY_FILENAME, mode="r") as subscribers:
        found = False
        for i in subscribers:
            if not str(update.message.chat_id) in i:
                lines.append(i)
            else:
                found = True
    if found:
        with open(SUBSCRIBED_EXPIRY_FILENAME, mode="w") as subscribers:
            subscribers.writelines(lines)
        message = "You were correctly unsubscribed."
    else:
        message = "You are not currently subscribed. \
        Use /subscribe to subscribe."

    update.message.reply_text(message)


def check_expiry(bot, update=None):
    """
    Check in the stock for items that are expired or will be in the next 7 days
    """
    today = datetime.today()
    values = gs_get_all_values()[1:]
    # keeps values in next 7 days
    sensible = [v for v in values if ('NA' not in v[NUM_COL_EXPIRY]) and
                (parse(v[NUM_COL_EXPIRY]) - timedelta(days=7) < today)]
    still_good = [v for v in sensible if parse(v[NUM_COL_EXPIRY]) >= today]
    expired = [v for v in sensible if parse(v[NUM_COL_EXPIRY]) < today]

    line = "-->"+"{},\t\t"*(NUM_COLS-1) + "{}"
    message = ""
    if not still_good:
        message += "No good will be expired in the next 7 days\n###########\n"
    else:
        message += "The following good(s) will be expired in the next week:\n"
        message += "\n".join([line.format(elem[NUM_COL_NAME],
                                          elem[NUM_COL_QTY],
                                          elem[NUM_COL_UNIT],
                                          elem[NUM_COL_EXPIRY])
                              for elem in still_good])
        message += "\n###########\n"
    if not expired:
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
        with open(SUBSCRIBED_EXPIRY_FILENAME, mode='r') as subscribers:
            for user_id in subscribers:
                update.message.reply_text(message)
    else:
        update.message.reply_text(message)


########################
# Google Sheet functions
########


def gs_append_value(value):
    """
    GOOGLE SHEET FUNCTION
    Append a new item in the stock
    """
    service = gs_get_service()
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


def gs_get_service():
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


def gs_get_values_response():
    """
    GOOGLE SHEET FUNCTION
    Return raw google response for all the values in stock
    """
    service = gs_get_service()
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
    return response


def gs_get_values_from_response(response):
    """
    GOOGLE SHEET FUNCTION
    From the JSON response,, return the value
    """
    values = [x[0].lower() for x in response['valueRanges'][0]
              ['valueRange']['values'] if len(x) > 0]
    with_position = dict(enumerate(values))
    return with_position


def gs_get_all_values():
    """
    GOOGLE SHEET FUNCTION
    Get all the items and values in stock
    """
    result = gs_get_service().spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=VALUES_RANGE_COLS).execute()
    values = result.get('values', [])
    if not values:
        print('No data found.')
    else:
        return values


def gs_update_value(row, value, comment=False):
    """
    GOOGLE SHEET FUNCTION
    Update the values of an object in stock
    """
    service = gs_get_service()
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
    return response

###########################
# Begin bot


CLIC_BOT = Bot(token=TOKEN, request=Request(con_pool_size=8))
UPDATER = Updater(bot=CLIC_BOT)

# schedule.every().day.at("12:00").do(check_expiry, clic_bot)
# schedule.every(1).minutes.do(check_expiry, clicBot)


DISPATCHER = UPDATER.dispatcher


DISPATCHER.add_handler(CommandHandler(
    'quit', tg_quit))
DISPATCHER.add_handler(CommandHandler(
    'list', tg_list_items))
DISPATCHER.add_handler(CommandHandler(
    'update', tg_update_value, pass_args=True))
DISPATCHER.add_handler(CommandHandler(
    'start', tg_start))
DISPATCHER.add_handler(CommandHandler(
    'help', tg_helper))
DISPATCHER.add_handler(CommandHandler(
    'new', tg_add_item, pass_args=True))
DISPATCHER.add_handler(CommandHandler(
    'identify', tg_get_chat_id, pass_args=True))
DISPATCHER.add_handler(CommandHandler(
    'search', tg_search_item, pass_args=True))
DISPATCHER.add_handler(CommandHandler(
    'subscribe', tg_subscribe_expiry))
DISPATCHER.add_handler(CommandHandler(
    'unsub', tg_unsubscribe_expiry))

# DISPATCHER.add_handler(CommandHandler(
#     'expire', check_expiry))

DISPATCHER.add_handler(MessageHandler(Filters.command, tg_unknown))

LOGGER.info("Starting polling")
UPDATER.start_polling()

######################
#       UTILS


def parse_list_commas(input_list):
    """
        Takes a list of strings, and separate it in strings following commas

        Example: parseListCommas(['this','is,','a','list,','of','strings'])
            >>> ['this is', 'a list', 'of strings']
    """
    if isinstance(input_list, list):
        return []
    placeholder = ['']
    for elem in input_list:
        if ',' in elem:
            elem = elem.replace(',', '')
            placeholder[-1] += elem
            placeholder.append('')
        else:
            placeholder[-1] += elem + " "
        # print(placeholder)
    placeholder[-1] = placeholder[-1][:-1]  # remove trailing space
    return placeholder


while True:
    schedule.run_pending()
    time.sleep(30)
