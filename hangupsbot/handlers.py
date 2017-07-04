"""Hangups conversationevent handler with custom pluggables for plugins"""

import logging
import shlex
import asyncio
import inspect
import time
import uuid

import hangups
import hangups.parsers

import plugins
from commands import command
from event import (GenericEvent, TypingEvent, WatermarkEvent, ConversationEvent)
from exceptions import HangupsBotExceptions


logger = logging.getLogger(__name__)


class EventHandler(object):
    """Handle Hangups conversation events

    Args:
        bot: HangupsBot instance
    """
    def __init__(self, bot):
        self.bot = GenericEvent.bot = bot
        self.bot_command = ['/bot']

        self._reprocessors = {}

        self._passthrus = {}
        self._contexts = {}
        self._image_ids = {}
        self._executables = {}

        self.pluggables = { "allmessages": [],
                            "call": [],
                            "membership": [],
                            "message": [],
                            "rename": [],
                            "history": [],
                            "sending":[],
                            "typing": [],
                            "watermark": [] }


        plugins.register_shared("reprocessor.attach_reprocessor",
                                self.attach_reprocessor)

        plugins.register_shared("chatbridge.behaviours", {})

        _conv_list = bot._conv_list     # pylint: disable=protected-access
        _conv_list.on_event.add_observer(self._handle_event)
        _conv_list.on_typing.add_observer(self._handle_status_change)
        _conv_list.on_watermark_notification.add_observer(
            self._handle_status_change)

    def register_handler(self, function, type="message", priority=50, extra_metadata=None):
        """
        register hangouts event handler
        * extra_metadata is function-specific, and will be added along with standard plugin-defined metadata
        * depending on event type, may perform transparent conversion of function into coroutine for convenience
          * reference to original function is stored as part of handler metadata
        * returns actual handler that will be used
        """

        extra_metadata = extra_metadata or {}
        extra_metadata["function.original"] = function

        # determine the actual handler function that will be registered
        _handler = function
        if type in ["allmessages", "call", "membership", "message", "rename", "history", "typing", "watermark"]:
            if not asyncio.iscoroutine(function):
                _handler = asyncio.coroutine(_handler)
        elif type in ["sending"]:
            if asyncio.iscoroutine(_handler):
                raise RuntimeError("{} handler cannot be a coroutine".format(type))
        else:
            raise ValueError("unknown event type for handler: {}".format(type))

        current_plugin = plugins.tracking.current

        # build handler-specific metadata
        _metadata = {}
        if current_plugin["metadata"] is None:
            # late registration - after plugins.tracking.end(), metadata key is reset to None
            _metadata = extra_metadata
        else:
            _metadata.update(current_plugin["metadata"])
            _metadata.update(extra_metadata)

        if not _metadata.get("module"):
            raise ValueError("module not defined")
        if not _metadata.get("module.path"):
            raise ValueError("module.path not defined")

        self.pluggables[type].append((_handler, priority, _metadata))
        self.pluggables[type].sort(key=lambda tup: tup[1])

        plugins.tracking.register_handler(_handler, type, priority, module_path=_metadata["module.path"])

        return _handler

    def deregister_handler(self, function, type=None, strict=True):
        """
        deregister a handler and stop processing it on events
        * also removes it from plugins.tracking
        * highly recommended to supply type (e.g. "sending", "message", etc) for optimisation
        """

        if type is None:
            type = list(self.pluggables.keys())
        elif isinstance(type, str):
            type = [ type ]
        elif isinstance(type, list):
            pass
        else:
            raise TypeError("invalid type {}".format(repr(type)))

        for t in type:
            if t not in self.pluggables and strict is True:
                raise ValueError("type {} does not exist".format(t))
            for h in self.pluggables[t]:
                # match by either a wrapped coroutine or original source function
                if h[0] == function or h[2]["function.original"] == function:
                    # remove from tracking
                    plugins.tracking.deregister_handler(h[0], module_path=h[2]["module.path"])

                    # remove from being processed
                    logger.debug("deregister {} handler {}".format(t, h))
                    self.pluggables[t].remove(h)

                    return # remove first encountered only

        if strict:
            raise ValueError("{} handler(s) {}".format(type, function))

    def register_handler(self, function, pluggable="message", priority=50,
                         **kwargs):
        """register an event handler

        Args:
            function: callable, the handling function/coro
            pluggable: string, a pluggable of .pluggables
            priority: int, lower priorities receive the event earlier
            kwargs: dict, legacy to catch the positional argument 'type'

        Raises:
            KeyError: unknown pluggable specified
        """
        if 'type' in kwargs:
            pluggable = kwargs['type']
            logger.warning('The positional argument "type" will be removed at '
                           'any time soon.', stack_info=True)

        # a handler may use not all args or kwargs, inspect now and filter later
        expected = inspect.signature(function).parameters
        names = list(expected)

        current_plugin = plugins.tracking.current
        self.pluggables[pluggable].append(
            (function, priority, current_plugin["metadata"], expected, names))
        # sort by priority
        self.pluggables[pluggable].sort(key=lambda tup: tup[1])
        plugins.tracking.register_handler(function, pluggable, priority)

    def register_passthru(self, variable):
        _id = str(uuid.uuid4())
        self._passthrus[_id] = variable
        return _id

    def register_context(self, context):
        """register a message context that can be later attached again

        Args:
            context: dict, no keys are required

        Returns:
            string, a unique identifier for the context
        """
        context_id = None
        while context_id is None or context_id in self._contexts:
            context_id = str(uuid.uuid4())
        self._contexts[context_id] = context
        return context_id

    def register_reprocessor(self, func):
        """register a function that can be called later

        Args:
            func: a callable that takes three args: bot, event, command

        Returns:
            string, a unique identifier for the callable
        """
        reprocessor_id = None
        while reprocessor_id is None or reprocessor_id in self._reprocessors:
            reprocessor_id = str(uuid.uuid4())
        self._reprocessors[reprocessor_id] = func
        return reprocessor_id

    def attach_reprocessor(self, func, return_as_dict=None):
        """connect a func to an identifier to reprocess the event on receive

        reprocessor: map func to a hidden annotation to a message.
        When the message is sent and subsequently received by the bot, it will
        be passed to the func, which can modify the event object by reference
        before it runs through the event processing

        Args:
            func: callable that takes three arguments: bot, event, command
            return_as_dict: legacy code
        """
        #pylint:disable=unused-argument
        reprocessor_id = self.register_reprocessor(func)
        return {"id": reprocessor_id,
                "callable": func}

    # handler core

    async def image_uri_from(self, image_id, callback, *args, **kwargs):
        """retrieve a public url for an image upload

        Args:
            image_id: int, upload id of a previous upload
            callback: coro, awaitable callable
            args: tuple, positional arguments for the callback
            kwargs: dict, keyword arguments for the callback

        Returns:
            boolean, False if no url was awaitable after 60sec, otherwise True
        """
        #TODO(das7pad) refactor plugins to use bot._client.image_upload_raw

        # there was no direct way to resolve an image_id to the public url
        # without posting it first via the api. other plugins and functions can
        # establish a short-lived task to wait for the image id to be posted,
        # and retrieve the url in an asyncronous way"""

        ticks = 0
        while True:
            if image_id not in self._image_ids:
                await asyncio.sleep(1)
                ticks = ticks + 1
                if ticks > 60:
                    return False
            else:
                await callback(self._image_ids[image_id], *args, **kwargs)
                return True

    async def run_reprocessor(self, reprocessor_id, event, *args, **kwargs):
        """reprocess the event with the callable that was attached on sending

        Args:
            reprocessor_id: string, a found reprocessor id
            event: hangupsbot event instance
        """
        reprocessor = self._reprocessors.get(reprocessor_id, pop=True)
        if reprocessor is None:
            return

        is_coroutine = asyncio.iscoroutinefunction(reprocessor)
        logger.info("reprocessor uuid found: %s coroutine=%s",
                    reprocessor_id, is_coroutine)
        if is_coroutine:
            await reprocessor(self.bot, event, reprocessor_id, *args, **kwargs)
        else:
            reprocessor(self.bot, event, reprocessor_id, *args, **kwargs)

    @asyncio.coroutine
    def _handle_chat_message(self, event):
        """Handle an incoming conversation event

        - auto-optin opt-outed users if the event is in a 1on1
        - run connected event-reprocessor
        - forward the event to handlers:
            - allmessages, all events
            - message, if user is not the bot user
        - handle the text as command, if the user is not the bot user

        Args:
            event: event.ConversationEvent instance

        Raises:
            exceptions.SuppressEventHandling: do not handle the event at all
        """
        if event.text:
            if event.user.is_self:
                event.from_bot = True
            else:
                event.from_bot = False

            """EventAnnotation - allows metadata to survive a trip to Google"""

            event.passthru = {}
            event.context = {}
            for annotation in event.conv_event._event.chat_message.annotation:
                if annotation.type == 1025:
                    # reprocessor - process event with hidden context from handler.attach_reprocessor()
                    yield from self.run_reprocessor(annotation.value, event)
                elif annotation.type == 1026:
                    if annotation.value in self._passthrus:
                        event.passthru = self._passthrus[annotation.value]
                        del self._passthrus[annotation.value]
                elif annotation.type == 1027:
                    if annotation.value in self._contexts:
                        event.context = self._contexts[annotation.value]
                        del self._contexts[annotation.value]

            """auto opt-in - opted-out users who chat with the bot will be opted-in again"""
            if not event.from_bot and self.bot.conversations.catalog[event.conv_id]["type"] == "ONE_TO_ONE":
                if self.bot.memory.exists(["user_data", event.user.id_.chat_id, "optout"]):
                    optout = self.bot.memory.get_by_path(["user_data", event.user.id_.chat_id, "optout"])
                    if isinstance(optout, bool) and optout:
                        yield from command.run(self.bot, event, *["optout"])
                        logger.info("auto opt-in for {}".format(event.user.id_.chat_id))
                        return

            """map image ids to their public uris in absence of any fixed server api
               XXX: small memory leak over time as each id gets cached indefinitely"""

            if( event.passthru
                    and "original_request" in event.passthru
                    and "image_id" in event.passthru["original_request"]
                    and event.passthru["original_request"]["image_id"]
                    and len(event.conv_event.attachments) == 1 ):

                _image_id = event.passthru["original_request"]["image_id"]
                _image_uri = event.conv_event.attachments[0]

                if _image_id not in self._image_ids:
                    self._image_ids[_image_id] = _image_uri
                    logger.info("associating image_id={} with {}".format(_image_id, _image_uri))

            """first occurence of an actual executable id needs to be handled as an event
               XXX: small memory leak over time as each id gets cached indefinitely"""

            if( event.passthru and "executable" in event.passthru and event.passthru["executable"] ):
                if event.passthru["executable"] not in self._executables:
                    original_message = event.passthru["original_request"]["message"]
                    linked_hangups_user = event.passthru["original_request"]["user"]
                    logger.info("current event is executable: {}".format(original_message))
                    self._executables[event.passthru["executable"]] = time.time()
                    event.from_bot = False
                    event.text = original_message
                    event.user = linked_hangups_user

            yield from self.run_pluggable_omnibus("allmessages", self.bot, event, command)
            if not event.from_bot:
                yield from self.run_pluggable_omnibus("message", self.bot, event, command)
                yield from self._handle_command(event)

    async def _handle_command(self, event):
        """Handle command messages

        Args:
            event: event.ConversationEvent instance
        """
        if not event.text:
            return

        bot = self.bot

        # is commands_enabled?
        config_commands_enabled = bot.get_config_suboption(event.conv_id,
                                                           'commands_enabled')
        tagged_ignore = "ignore" in bot.tags.useractive(event.user_id.chat_id,
                                                        event.conv_id)

        if not config_commands_enabled or tagged_ignore:
            admins_list = bot.get_config_suboption(event.conv_id, 'admins')
            # admins always have commands enabled
            if event.user_id.chat_id not in admins_list:
                return

        # check that a bot alias is used e.g. /bot
        if not event.text.split()[0].lower() in self.bot_command:
            if (bot.conversations[event.conv_id]["type"] == "ONE_TO_ONE"
                    and bot.config.get_option('auto_alias_one_to_one')):
                # Insert default alias if not already present
                event.text = u" ".join((self.bot_command[0], event.text))
            else:
                return

        # Parse message, convert non-breaking space in Latin1 (ISO 8859-1)
        event.text = event.text.replace(u'\xa0', u' ')
        try:
            line_args = shlex.split(event.text, posix=False)
        except ValueError:
            logger.exception('shlex.split failed parsing "%s"', event.text)
            line_args = event.text.split()

        commands = command.get_available_commands(bot, event.user_id.chat_id,
                                                  event.conv_id)

        supplied_command = line_args[1].lower()
        if (supplied_command in commands["user"] or
                supplied_command in commands["admin"]):
            pass
        elif supplied_command in command.commands:
            await command.blocked_command(bot, event, *line_args[1:])
            return
        else:
            await command.unknown_command(bot, event, *line_args[1:])
            return

        # Run command
        results = await command.run(bot, event, *line_args[1:])

        if "acknowledge" in dir(event):
            for id_ in event.acknowledge:
                await self.run_reprocessor(id_, event, results)

    async def run_pluggable_omnibus(self, name, *args, **kwargs):
        """forward args to a group of handler which were registered for the name

        Args:
            name: string, a key in .pluggables
            args: tuple, positional arguments for each handler
            kwargs: dict, keyword arguments for each handler

        Raises:
            KeyError: unknown pluggable specified
            HangupsBotExceptions.SuppressEventHandling: do not handle further
        """
        try:
            for function, dummy, meta, expected, names in self.pluggables[name]:
                message = ["%s: %s.%s" % (name, meta['module.path'],
                                          function.__name__)]

                try:
                    # a handler may use not all args or kwargs, filter here
                    positional = (args[num] for num in range(len(args))
                                  if (len(names) > num and (
                                      expected[names[num]].default ==
                                      inspect.Parameter.empty or
                                      names[num] not in kwargs)))
                    keyword = {key: value for key, value in kwargs.items()
                               if key in names}

                    logger.debug(message[0])
                    result = function(*positional, **keyword)
                    if asyncio.iscoroutinefunction(function):
                        await result
                except HangupsBotExceptions.SuppressHandler:
                    # skip this pluggable, continue with next
                    message.append("SuppressHandler")
                    logger.debug(" : ".join(message))
                except (HangupsBotExceptions.SuppressEventHandling,
                        HangupsBotExceptions.SuppressAllHandlers):
                    # handle requested to skip all pluggables
                    raise
                except: # capture all Exceptions   # pylint: disable=bare-except
                    # exception is not related to the handling of this
                    # pluggable, log and continue with the next handler
                    message.append("args=" + str([str(arg) for arg in args]))
                    message.append("kwargs=" + str(kwargs))
                    logger.exception(" : ".join(message))

        except HangupsBotExceptions.SuppressAllHandlers:
            # skip all other pluggables, but let the event continue
            message.append("SuppressAllHandlers")
            logger.debug(" : ".join(message))

        except HangupsBotExceptions.SuppressEventHandling:
            # handle requested to do not handle the event at all, skip all
            # handler and do not continue with event handling in the parent
            raise

    async def _handle_event(self, conv_event):
        """Handle conversation events

        Args:
            conv_event: hangups.conversation_event.ConversationEvent instance
        """
        event = ConversationEvent(conv_event)

        if isinstance(conv_event, hangups.ChatMessageEvent):
            pluggable = None

        elif isinstance(conv_event, hangups.MembershipChangeEvent):
            pluggable = "membership"

        elif isinstance(conv_event, hangups.RenameEvent):
            pluggable = "rename"

        elif isinstance(conv_event, hangups.OTREvent):
            pluggable = "history"

        elif isinstance(conv_event, hangups.HangoutEvent):
            pluggable = "call"

        else:
            # Unsupported Events:
            # * GroupLinkSharingModificationEvent
            # https://github.com/tdryer/hangups/blob/master/hangups/conversation_event.py
            logger.warning("unrecognised event type: %s", type(conv_event))
            return

        if pluggable is not None or event.conv_id not in self.bot.conversations:
            # rebuild permamem for a conv including conv-name, participants, otr
            # if the event is not a message or the conv is missing in permamem
            await self.bot.conversations.update(event.conv, source="event")

        if pluggable is None:
            asyncio.ensure_future(self._handle_chat_message(event))
            return

        asyncio.ensure_future(self.run_pluggable_omnibus(
            pluggable, self.bot, event, command))

    async def _handle_status_change(self, state_update):
        """run notification handler for a given state_update

        Args:
            state_update: hangups.parsers.TypingStatusMessage or
             hangups.parsers.WatermarkNotification instance
        """
        if isinstance(state_update, hangups.parsers.TypingStatusMessage):
            pluggable = "typing"
            event = TypingEvent(state_update)

        else:
            pluggable = "watermark"
            event = WatermarkEvent(state_update)

        asyncio.ensure_future(self.run_pluggable_omnibus(
            pluggable, self.bot, event, command))


class HandlerBridge:
    """shim for xmikosbot handler decorator"""

    def set_bot(self, bot):
        """shim requires a reference to the bot's actual EventHandler to register handlers"""
        self.bot = bot

    def register(self, *args, priority=10, event=None):
        """Decorator for registering event handler"""

        # make compatible with this bot fork
        scaled_priority = priority * 10 # scale for compatibility - xmikos range 1 - 10
        if event is hangups.ChatMessageEvent:
            event_type = "message"
        elif event is hangups.MembershipChangeEvent:
            event_type = "membership"
        elif event is hangups.RenameEvent:
            event_type = "rename"
        elif event is hangups.OTREvent:
            event_type = "history"
        elif type(event) is str:
            event_type = str # accept all kinds of strings, just like register_handler
        else:
            raise ValueError("unrecognised event {}".format(event))

        def wrapper(func):
            def thunk(bot, event, command):
                # command is an extra parameter supplied in this fork
                return func(bot, event)

            # Automatically wrap handler function in coroutine
            compatible_func = asyncio.coroutine(thunk)
            self.bot._handlers.register_handler(compatible_func, event_type, scaled_priority)
            return compatible_func

        # If there is one (and only one) positional argument and this argument is callable,
        # assume it is the decorator (without any optional keyword arguments)
        if len(args) == 1 and callable(args[0]):
            return wrapper(args[0])
        else:
            return wrapper

handler = HandlerBridge()
