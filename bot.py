import logging

from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

import botFuncs

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
updater = Updater(token='512461432:AAFylLRostkwNvAxP43IcHI1cJ5NpRVqZko')
dispatcher = updater.dispatcher

#actual functions
def addHandlers():
    start_handler = CommandHandler('start',botFuncs.start)
    quit_handler = CommandHandler('quit', botFuncs.quit)
    list_handler = CommandHandler('list', botFuncs.listItems)
    unknown_handler = MessageHandler(Filters.command, botFuncs.unknown)
    echo_handler = MessageHandler(Filters.text, botFuncs.echo)
    help_handler = CommandHandler('help',botFuncs.helper)
    addItem_handler = CommandHandler('new',botFuncs.addItem, pass_args=True)
    
    dispatcher.add_handler(start_handler)
    dispatcher.add_handler(quit_handler)
    dispatcher.add_handler(list_handler)
    dispatcher.add_handler(echo_handler)
    dispatcher.add_handler(help_handler)
    dispatcher.add_handler(addItem_handler)
    ##ALWAYS LAST !!
    dispatcher.add_handler(unknown_handler)
    print("All handlers added !")

def main():
    addHandlers()
    updater.start_polling(clean=True)
    updater.idle()

if __name__ == "__main__":
    main()
