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
# import time
from datetime import datetime, timedelta

# import schedule
# import yaml
from googleapiclient.discovery import build
from dateutil.parser import parse
from httplib2 import Http
from oauth2client import client, file, tools
from telegram import Bot
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater
# from telegram.utils.helpers import escape_markdown
from telegram.utils.request import Request

from utils import open_yaml, setup_logging

# from os.path import isfile
# from pprint import pprint


#####################
# Constants

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

############################
# Telegram functions

class Telegram():
    """
    Represent the bot class
    """

    def __init__(self, config_file):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Setting up Telegram object !")
        try:
            self.logger.info("Opening config file")
            self.config = open_yaml(config_file)
        except FileNotFoundError:
            self.logger.critical("Configuration file not found, exiting")
            sys.exit()
        token = self.config['CLICSTOCK_TOKEN']
        self.owner_id = self.config['OWNER_ID']
        clic_bot = Bot(token=token, request=Request(con_pool_size=8))
        self.updater = Updater(bot=clic_bot)
        self.subs_expiry = self.config['SUBSCRIBED_EXPIRY_FILENAME']
        self.stock = Sheets()
        self.odj = Doc()
        self.dispatcher = self.updater.dispatcher

        self.add_handlers()
        # BOTNAME = self.config['CLICSTOCK_BOTNAME']

    def add_handlers(self):
        """
        Add the handlers to the bot
        """
        self.dispatcher.add_handler(CommandHandler('start',
                                                   self.tg_start))
        self.dispatcher.add_handler(CommandHandler('quit',
                                                   self.tg_quit))
        self.dispatcher.add_handler(CommandHandler('list',
                                                   self.tg_list_items))
        self.dispatcher.add_handler(CommandHandler('update',
                                                   self.tg_update_value,
                                                   pass_args=True))
        self.dispatcher.add_handler(CommandHandler('help',
                                                   self.tg_helper))
        self.dispatcher.add_handler(CommandHandler('new',
                                                   self.tg_add_item,
                                                   pass_args=True))
        self.dispatcher.add_handler(CommandHandler('identify',
                                                   self.tg_get_chat_id,
                                                   pass_args=True))
        self.dispatcher.add_handler(CommandHandler('search',
                                                   self.tg_search_item,
                                                   pass_args=True))
        self.dispatcher.add_handler(CommandHandler('subscribe',
                                                   self.tg_subscribe_expiry))
        self.dispatcher.add_handler(CommandHandler('unsub',
                                                   self.tg_unsubscribe_expiry))
        self.dispatcher.add_handler(MessageHandler(Filters.command,
                                                   self.tg_unknown))

    def tg_start(self, _, update):
        """
        TELEGRAM FUNCTION
        Mandatory bot starting function
        """
        self.logger.info("User %d started !", update.message.chat_id)
        update.message.reply_text('Hi!')

    def tg_quit(self, _, update):
        """
        TELEGRAM FUNCTION
        Stop the bot. For admin only.
        """
        if update.message.chat_id != self.owner_id:
            update.message.reply_text("Sorry, you can't perform this task. "
                                      "You're not an admin.")
        else:
            update.message.reply_text("Thanks for talking with me. By by !")
            self.updater.stop()
            sys.exit()

    def tg_list_items(self, _, update):
        """
        TELEGRAM FUNCTION
        List all items in the stock
        """
        values = self.stock.gs_get_all_values()
        columns = values[0]
        items = values[1:]
        self.pprint_tg(update, items, columns=columns)

    def pprint_tg(self, update,
                  items_list,
                  header="The following items are in stock:\n",
                  columns=None):
        """
        Send a message formatted nicely
        """
        columns = self.config['COLS_NAMES'] if columns is None else columns
        line = "{},\t\t"*(self.stock.num_cols-1) + "{}"
        content = "\n\n".join([line.format(elem[self.stock.num_col_name],
                                           elem[self.stock.num_col_qty],
                                           elem[self.stock.num_col_unit],
                                           elem[self.stock.num_col_expiry])
                               for elem in items_list])
        cols = line.format(*columns)
        update.message.reply_text(header+cols+"\n"+content)

    def tg_unknown(self, _, update):
        """
        TELEGRAM FUNCTION
        Reaction when the command is unknown
        """
        update.message.reply_text("Sorry, I didn't understand that command.")

    def tg_helper(self, _, update):
        """
        TELEGRAM FUNCTION
        Help the user
        """
        help_header = "Hi! This is the help message for ClicStock_Bot. \
        Here are the various commands you can use: \n\n"
        help_body = "\n".join(["{}\t\t{}".format(x, COMMANDS[x])
                               for x in COMMANDS])
        update.message.reply_text(help_header+help_body)

    def tg_add_item(self, _, update, args):
        """
        TELEGRAM FUNCTION
        Add an item to the stock
        """
        new_obj = parse_list_commas(args)
        if len(new_obj) < self.stock.min_num_cols or \
                len(new_obj) > self.stock.num_cols:

            message = "You need to specify the object, quantity, unit and " + \
                "optionally the expiry date (commas separated), no more"
            update.message.reply_text(message)
            return

        # at this point, we have between MIN_NUM_COLS and NUM_COLS columns
        try:  # always check the quantity
            new_obj[self.stock.num_col_qty] = float(
                new_obj[self.stock.num_col_qty])
            assert new_obj[self.stock.num_col_qty] >= 0
        except (ValueError, AssertionError):
            message = "Your second item (quantity) could not be understood \
            as a positive number. Please check."
            self.logger.warning('Chat id %d tried to add quantity %s',
                                update.message.chat_id,
                                new_obj[self.stock.num_col_qty])
            update.message.reply_text(message)
            return

        if len(new_obj) == self.stock.num_cols:
            # if date is specified, try to parse
            try:
                new_obj[self.stock.num_col_expiry] = parse(
                    new_obj[self.stock.num_col_expiry])
            except ValueError:
                message = "Your last item (expiration date) could not \
                be understood as a date. Please check."
                self.logger.warning('Chat id %s tried to add expire date %s',
                                    update.message.chat_id,
                                    new_obj[self.stock.num_col_expiry])
                update.message.reply_text(message)
                return
        else:  # if no date specified, add NA
            new_obj += ['NA']

        items = self.stock.gs_get_values_from_response(
            self.stock.gs_get_values_response()).values()

        if new_obj[self.stock.num_col_name].lower() in items:
            message = "This item already exists in the stock"
        else:
            success = self.stock.gs_append_value(new_obj)
            if success['updates']['updatedCells'] == len(new_obj):
                message = "Successfully added this item"
            else:
                message = "Failed to add... please refer to an admin"
        update.message.reply_text(message)

    def tg_get_chat_id(self, _, update, args):
        """
        TELEGRAM FUNCTION
        Let a user be known to the admin
        """
        user_id = update.message.chat_id
        if args:
            self.logger.info("User with ID %d just identified himself as %s",
                             user_id, args[0])
        else:
            self.logger.info("User with ID %s just identified anonymously",
                             user_id)
        return user_id

    def tg_search_item(self, _, update, args):
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

        items = self.stock.gs_get_all_values()
        result = []
        for i in items[1:]:
            if i[self.stock.num_col_name].lower().find(word.lower()) >= 0:
                result += [i]

        self.pprint_tg(update, result)

    def tg_update_value(self, _, update, args):
        """
        TELEGRAM FUNCTION
        Update an item in the stock (e.g. its quantity in stock)
        """
        # Arguments parsing
        # Required positions :[name (str), +/- quantity (int), {comment}]
        parsed = parse_list_commas(args)
        if len(parsed) < self.stock.min_num_cols:
            update.message.reply_text("You did not specify enough arguments."
                                      "Specify at least Item and Quantity "
                                      "(comma separated)")
            return

        obj = parsed[0].lower()

        # interpret quantity as relative or absolute
        try:
            quantity = int(parsed[1])
        except ValueError:
            update.message.reply_text(self.config['ERROR_UPDATE_VALUE'])
            return
        relative = False
        if parsed[1][0] == '+' or parsed[1][0] == '-':
            relative = True

        # find index of value to update
        raw_values = self.stock.gs_get_all_values()
        values = list(itertools.zip_longest(*raw_values))
        print(values)
        index = [i for i, v in enumerate(values[0]) if v.lower() == obj]
        if not index:
            update.message.reply_text(
                self.config['ERROR_UPDATE_404'].format(obj))
            return
        elif len(index) > 1:
            header = self.config['ERROR_UPDATE_TOO_MANY_MATCH']
            names = index  # TODO keep only names
            self.pprint_tg(update, names, header)
            return
        obj_pos = index[0][0]  # TODO Check this is correct
        # find new value according to relativity
        new_val = quantity
        if relative:
            new_val += int(values[1][obj_pos])
        # update
        response = self.stock.gs_update_value(obj_pos+1, new_val)
        if response['responses'][0]['updatedCells'] == 1:
            update.message.reply_text(self.config['UPDATE_OK'])
        else:
            update.message.reply_text(self.config['UPDATE_NOT_OK'])

    def tg_subscribe_expiry(self, _, update):
        """
        TELEGRAM FUNCTION
        Subscribe a user to the expiry alerts
        """
        with open(self.subs_expiry, mode='r+') as subscribers:
            for i in subscribers:
                if i.strip() == str(update.message.chat_id):
                    message = "Sorry, you are already subscribed to this list."
                    update.message.reply_text(message)
                    return
            # here, we are at the end of the file, we can simply append
            ret = subscribers.write(str(update.message.chat_id)+"\n")
            if ret > 0:
                message = "You subscribes to this list! Congratulations"
            else:
                message = "Something wrong happened... contact an admin"
                update.message.reply_text(message)

    def tg_unsubscribe_expiry(self, _, update):
        """
        TELEGRAM FUNCTION
        Unsubscribe a user to the expiry alerts
        """
        to_keep = []
        with open(self.subs_expiry, mode="r") as subscribers:
            found = False
            for i in subscribers:
                if not str(update.message.chat_id) in i:
                    to_keep.append(i)
                else:
                    found = True
        if found:
            with open(self.subs_expiry, mode="w") as subscribers:
                subscribers.writelines(to_keep)
            message = "You were correctly unsubscribed."
        else:
            message = "You are not currently subscribed. \
            Use /subscribe to subscribe."

        update.message.reply_text(message)

    def check_expiry(self, bot, update=None):
        """
        Check in the stock for items that are expired or
        will be in the next 7 days
        """
        today = datetime.today()
        exp_col = self.stock.num_col_expiry
        values = self.stock.gs_get_all_values()[1:]
        # keeps values in next 7 days

        sensible = []
        for val in values:
            if ('NA' not in val[exp_col]) and \
                    (parse(val[exp_col]) - timedelta(days=7) < today):
                sensible.append(val)
        still_good = [val for val in sensible if parse(val[exp_col]) >= today]
        expired = [val for val in sensible if parse(val[exp_col]) < today]

        line = "-->"+"{},\t\t"*(self.stock.num_cols-1) + "{}"
        message = ""
        if not still_good:
            message += "No good will be expired in the " +\
                "next 7 days\n###########\n"
        else:
            message += "The following good(s) will be expired in " +\
                "the next week:\n"
            message += "\n".join([line.format(elem[self.stock.num_col_name],
                                              elem[self.stock.num_col_qty],
                                              elem[self.stock.num_col_unit],
                                              elem[self.stock.num_col_expiry])
                                  for elem in still_good])
            message += "\n###########\n"
        if not expired:
            message += "No good is currently expired\n###########\n"
        else:
            message += "The following good(s) already expired. SHAME !:\n"
            message += "\n".join([line.format(elem[self.stock.num_col_name],
                                              elem[self.stock.num_col_qty],
                                              elem[self.stock.num_col_unit],
                                              elem[self.stock.num_col_expiry])
                                  for elem in expired])
            message += "\n###########\n"
        if update is None:
            with open(self.subs_expiry, mode='r') as subs:
                for user_id in subs:
                    bot.send_message(chat_id=user_id, text=message)
        else:
            update.message.reply_text(message)


########################
# Google Sheet functions
########

class Google():
    """
    A class for all the Google objects. This should not be used per se,
    but used as a superclass for concrete google object
    """

    def __init__(self):
        """
        Start a google object. Initialize all that is common to any google
        object (doc, sheet, drive,...)
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initiating google object")
        try:
            self.logger.info("Reading config file")
            self.config = open_yaml("config.yaml")
        except FileNotFoundError:
            self.logger.critical("Config file not found")
            sys.exit()

    def get_credentials(self, scope):
        """ Setup the Sheets API"""
        store = file.Storage('credentials.json')
        credentials = store.get()
        if not credentials or credentials.invalid:
            print("Credentials invalid, renewing")
            flow = client.flow_from_clientsecrets(
                'client_secret.json', scope)
            credentials = tools.run_flow(flow, store)
        return credentials


class Doc(Google):
    """
    A subclass of Google: represents Google Doc objects
    """

    def __init__(self):
        super().__init__(args, kwargs)


class Sheets(Google):
    """
    A subclass of Google: represents Google Sheets objects
    """

    def __init__(self, *args, **kwargs):
        super().__init__(args, kwargs)
        self.spreadsheet_id = self.config['CLIC_SHEETID']
        self.scope = self.config['CLIC_SHEET_SCOPE']
        self.col_start = self.config['COL_START']
        self.col_end = self.config['COL_END']
        self.row_start = self.config['ROW_START']
        self.values_range = '{}!{}{}:{}{}'.format(
            self.config['SHEET_NAME'],
            self.col_start,
            self.row_start,
            self.col_end,
            self.row_start)
        self.values_range_cols = '{}!{}:{}'.format(
            self.config['SHEET_NAME'],
            self.col_start,
            self.col_end)
        self.min_num_cols = self.config['MANDATORY_COLS']
        self.min_num_cols_update = self.config['MANDATORY_COLS_UPDATE']
        self.num_cols = self.config['NUM_COLS']

        self.num_col_name = self.config['NUM_COL_NAME']
        self.num_col_qty = self.config['NUM_COL_QTY']
        self.num_col_unit = self.config['NUM_COL_UNIT']
        self.num_col_expiry = self.config['NUM_COL_EXPIRY']

    def gs_get_service(self):
        """
        Returns a google sheet service with which to work
        """
        credentials = self.get_credentials(self.config['CLIC_SHEET_SCOPE'])
        service = build('sheets', 'v4', http=credentials.authorize(
            Http()), cache_discovery=False)
        return service

    def gs_get_values_response(self):
        """
        GOOGLE SHEET FUNCTION
        Return raw google response for all the values in stock
        """
        service = self.gs_get_service()
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
            spreadsheetId=self.spreadsheet_id,
            body=body
        ).execute()
        return response

    def gs_append_value(self, value):
        """
        GOOGLE SHEET FUNCTION
        Append a new item in the stock
        """
        service = self.gs_get_service()
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
            spreadsheetId=self.spreadsheet_id,
            sheet_range=sheet_range,
            body=resource,
            valueInputOption="USER_ENTERED"
        ).execute()
        return response

    def gs_get_values_from_response(self, response):
        """
        GOOGLE SHEET FUNCTION
        From the JSON response,, return the value
        """
        values = [x[0].lower() for x in response['valueRanges'][0]
                  ['valueRange']['values'] if len(x) > 0]
        with_position = dict(enumerate(values))
        return with_position

    def gs_get_all_values(self):
        """
        GOOGLE SHEET FUNCTION
        Get all the items and values in stock
        """
        result = self.gs_get_service().spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=self.values_range_cols).execute()
        values = result.get('values', [])
        if not values:
            print('No data found.')
        else:
            return values

    def gs_update_value(self, row, value):
        """
        GOOGLE SHEET FUNCTION
        Update the values of an object in stock
        """
        service = self.gs_get_service()

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
            spreadsheetId=self.spreadsheet_id, body=body).execute()
        print(response)
        return response

###########################
# Begin bot


# schedule.every().day.at("12:00").do(check_expiry, clic_bot)
# schedule.every(1).minutes.do(check_expiry, clicBot)

def main():
    """
    Start the bot
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting polling")
    tg_bot = Telegram("config.yaml")
    tg_bot.updater.start_polling()
    tg_bot.updater.idle()
    # while True:
    #     schedule.run_pending()
    #     time.sleep(30)
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


if __name__ == "__main__":
    main()
