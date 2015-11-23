import asyncio, logging, json

import plugins

import cherrypy

logger = logging.getLogger(__name__)

def _initialise(bot):
    plugins.register_handler(_start_manager(bot))

def _start_manager(bot):
    """will host a basic plugin manager"""

    manager = bot.get_config_option('manager')

    try:
        port = manager["port"]
    except KeyError as e:
        logger.error("config.manager missing keyword", e)
        logger.info("using default port for manager.py: 9090")
        port = 9090

    cherrypy.config.update({'server.socket_port': port})
    # Start server
    cherrypy.tree.mount(PluginManager(bot), '/')
    cherrypy.engine.start()

class PluginManager(object):
    def __init__(self, bot):
        self._bot = bot

    def index(self):
        return "<b>Bot Configuration</b><br><a href='/plugins'>Plugin Manager</a>"

    @cherrypy.expose
    def plugins(self):
        all_plugins = plugins.retrieve_all_plugins()
        loaded_plugins = plugins.get_configured_plugins(self._bot)
        html = """<html>
        <head></head>
          <body>
            <b>Loaded Plugins</b><br>
            <form method="get" action="plugins_submit">"""
        for plugin in all_plugins:
            if plugin in loaded_plugins:
                checked = " checked"
            else:
                checked = ""
            html += "<input type=\"checkbox\" name=\"plugin\" value=\"{0}\"{1}> {0}<br>".format(plugin, checked)

        html += """
              <button type="submit">Save</button>
            </form>
          </body>
        </html>"""
        return html

    @cherrypy.expose
    def plugins_submit(self, plugin):
        print("Plugins: {}".format(plugin))
        self._bot.config.set_by_path(["plugins"], plugin)
        self._bot.config.save()
        self._bot.config.load()
        return "Plugins successfully updated!<br><a href='/'>Back to bot configuration</a>"

    index.exposed = True