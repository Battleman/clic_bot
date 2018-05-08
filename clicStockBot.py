#!/home/battleman/Programs/anaconda3/bin/python
import itertools
import json
import logging
import sys
from pprint import pprint

import telegram
import yaml
from apiclient.discovery import build
from httplib2 import Http
from oauth2client import client, file, tools
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

"""
#	Load the config file
#	Set the Botname / Token
"""
config_file = 'config.yaml'
# myfile = Path(config_file)
# if my_file.is_file():
with open(config_file) as fp:
    config = yaml.load(fp)
# else:
#     pprint('config.yaml file does not exists. Please make from config.sample.yaml file')
#     sys.exit()
TOKEN = config['CLICSTOCK_TOKEN']
BOTNAME = config['CLICSTOCK_BOTNAME']
SPREADSHEET_ID = config['CLIC_SHEETID']
SCOPE = config['CLIC_SHEET_SCOPE']
OWNER_ID = config['OWNER_ID']
VALUES_RANGE_START = config['CLICSTOCK_VALUES_STARTRANGE']

commands = {'list': 'List all items in stock',
            'help': 'This command help :)',
            'quit': 'stop the bot. For everyone. Forever.',
            'identify': 'Let the owner know your TG ID. Only useful for admins.',
            'new': 'Add an item to the stock'
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
    print("[LIST] raw values are:", values)
    titre = "{}\t\t{}\t\t{}\n".format(values[0][0], values[0][1], values[0][2])
    content = "\n\n".join(["{}\t\t{}\t\t{}".format(v[0], v[1], v[2]) if len(v) == 3
                           else "{}\t\t{}".format(v[0], v[1]) for v in values[1:] if len(v) > 1])
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
    items = gs_getValuesFromResponse(gs_getValuesResponse()).values()
    if args[0].lower() in items:
        message = "This item already exists in the stock"
    else:
        success = gs_appendValue(args)
        if(success['updates']['updatedCells'] == len(args)):
            message = "Successfully added this item"
        else:
            message = "Failed to add.. please refer to an admin"
    bot.send_message(chat_id=update.message.chat_id, text=message)


def tg_getChatID(bot, update, args):
    id = update.message.chat_id
    if len(args) > 0:
        print("User with ID {} just identified himself as {}".format(
            id, args[0]))
    else:
        print("User with ID {} just identified himself anonymously".format(id))
    return id


def tg_updateValue(bot, update, args):
    # Arguments parsing
    parsed = parseListCommas(args)
    obj = parsed[0].lower()  # TODO need to adapt for spaces in names

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
                         text=config['ERROR_UPDATE_404'].format())
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

########################
#   Google Sheet functions


def gs_appendValue(vals):
    service = gs_getService()
    if len(vals) == 2:
        vals += [""]
    bdy = [[vals[0], vals[1], vals[2]]]
    resource = {
        "majorDimension": "ROWS",
        "values": bdy
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
    print("Response to the getValueRange is\n", response)
    return response


def gs_getValuesFromResponse(response):
    values = [x[0].lower() for x in response['valueRanges'][0]
              ['valueRange']['values'] if len(x) > 0]
    withPos = dict(enumerate(values))
    print(withPos)
    return withPos


def gs_getAllValues():
    range = "Stock!A:C"
    result = gs_getService().spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                         range=range).execute()
    values = result.get('values', [])
    if not values:
        print('No data found.')
    else:
        return values


def gs_UpdateValue(row, value, comment=False):
    service = gs_getService()
    if comment:
        val, com = value
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

###########################
# Begin bot


clicBot = telegram.Bot(token=TOKEN)
updater = Updater(bot=clicBot)

dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler('quit', tg_quit))
dispatcher.add_handler(CommandHandler('list', tg_listItems))
dispatcher.add_handler(MessageHandler(Filters.text, tg_echo))
dispatcher.add_handler(CommandHandler(
    'update', tg_updateValue, pass_args=True))
dispatcher.add_handler(CommandHandler('start', tg_start))
dispatcher.add_handler(CommandHandler('help', tg_helper))
dispatcher.add_handler(CommandHandler('new', tg_addItem, pass_args=True))
dispatcher.add_handler(CommandHandler(
    'identify', tg_getChatID, pass_args=True))
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
        print(placeholder)
    placeholder[-1] = placeholder[-1][:-1]  # remove trailing space
    return placeholder
