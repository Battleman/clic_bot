from pprint import pprint
import yaml
from apiclient.discovery import build
from httplib2 import Http
from oauth2client import client, file, tools
import json
import logging
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater
import telegram
import sys

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
VALUES_RANGE = "Stock!A1:C4"
commands = {'list':'List all items in stock', 'help':'This command help :)','quit':'stop the bot. For everyone. Forever.'}


"""
# Configure Logging
"""
FORMAT = '%(asctime)s -- %(levelname)s -- %(module)s %(lineno)d -- %(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT)
logger = logging.getLogger('root')
logger.info("Running "+sys.argv[0])

def tg_start(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="I'm a bot, please talk to me!")    
def tg_quit(bot, update):
    if update.message.chat_id != OWNER_ID:
        bot.send_message(chat_id=update.message.chat_id, text="Sorry, you can't perform this task. You're not an admin.")
    else:
        bot.send_message(chat_id=update.message.chat_id, text="Thanks for talking with me. By by !")
        updater.stop()
        sys.exit()
def tg_listItems(bot, update):
    values = gs_getAllValues()
    titre = "{}\t\t{}\t\t{}\n".format(values[0][0],values[0][1],values[0][2])
    content="\n".join(["{}\t\t{}\t\t{}".format(v[0],v[1],v[2]) for v in values[1:]])
    s = titre + content
    bot.send_message(chat_id=update.message.chat_id, text="The following articles are in stock:\n{}".format(s))
def tg_unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="Sorry, I didn't understand that command.")
def tg_helper(bot, update):
    helpHeader = "Hi! This is the help message for ClicStock_Bot. Here are the various commands you can use:\n\n"
    helpBody = "\n".join(["{}\t\t{}".format(x, commands[x]) for x in commands])
    bot.send_message(chat_id=update.message.chat_id, text=helpHeader+helpBody)
def tg_echo(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=update.message.text)
def tg_addItem(bot, update, args):
    success = gs_appendValue(args)
    print("Success is", success)
    if(success):
        message = "Successfully added this item"
    else:
        message = "Failed to add.. please refer to an admin"
    bot.send_message(chat_id=update.message.chat_id, text=message)
def tg_getChatID(bot, update): 
    id = update.message.chat_id
    print("User with ID {} just identified himself".format(id))
    return id

"""
#   Google Sheet functions
"""
def gs_appendValue(vals):
    service = gs_getService()
    bdy = [[vals[0], vals[1], vals[2]]]
    resource = {
                "majorDimension": "ROWS",
                "values": bdy
        }
    range = "Stock!A7:C7"
    response = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=range,
        body=resource,
        valueInputOption="USER_ENTERED"
    ).execute()
    return response

def gs_init():
    print("Scope is", SCOPE)
    store = file.Storage('credentials.json')
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('client_secret.json', SCOPE)
        creds = tools.run_flow(flow, store)
    service = build('sheets', 'v4', http=creds.authorize(Http()), cache_discovery=False)


def gs_getService():
        """ Setup the Sheets API"""
        store = file.Storage('credentials.json')
        creds = store.get()
        if not creds or creds.invalid:
            flow = client.flow_from_clientsecrets('client_secret.json', SCOPE)
            creds = tools.run_flow(flow, store)
        service = build('sheets', 'v4', http=creds.authorize(Http()), cache_discovery=False)
        return service
def gs_getValuesRange():
    pass

def gf_getNewLineRange():
    pass

def gs_getAllValues():
        result = gs_getService().spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
                                                    range=VALUES_RANGE).execute()
        values = result.get('values', [])
        if not values:
            print('No data found.')
        else:
            return values


###########################
# Begin bot

clicBot = telegram.Bot(token = TOKEN)
updater = Updater(bot=clicBot, workers=10)

dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler('quit', tg_quit))
dispatcher.add_handler(CommandHandler('list', tg_listItems))
dispatcher.add_handler(MessageHandler(Filters.text, tg_echo))
dispatcher.add_handler(CommandHandler('start',tg_start))
dispatcher.add_handler(CommandHandler('help',tg_helper))
dispatcher.add_handler(CommandHandler('new',tg_addItem, pass_args=True))
dispatcher.add_handler(CommandHandler('identify',tg_getChatID))
dispatcher.add_handler(MessageHandler(Filters.command, tg_unknown))

gs_init()
logger.info("Starting polling")
updater.start_polling()

######################
#       UTILS

