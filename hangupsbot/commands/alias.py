"""provide the ability to tag a conversation with an unique alias"""

__author__ = 'kilr00y@esthar.net, das7pad@outlook.com'

import functools

import plugins

from . import Help

HELP = {
    'gethoalias': _('Get the alias for the current or given conversation\n'
                    '{bot_cmd} gethoalias\nadmin-only:\n{bot_cmd} gethoalias '
                    '<convID>\n{bot_cmd} gethoalias all'),
    'sethoalias': _('Set or unset the alias for the current or given '
                    'conversation\n{bot_cmd} sethoalias <alias>\n{bot_cmd} '
                    'sethoalias none\n{bot_cmd} sethoalias <alias> <convID>\n'
                    '{bot_cmd} sethoalias none <convID>')
}

def _initialise(bot):
    """register the commands and help, shareds on the aliases

    Args:
        bot: HangupsBot instance
    """
    bot.memory.validate({'hoalias': {}})

    plugins.register_user_command(['gethoalias'])
    plugins.register_admin_command(['sethoalias'])
    plugins.register_help(HELP)

    plugins.register_shared('convid2alias', functools.partial(get_alias, bot))
    plugins.register_shared('alias2convid', functools.partial(get_convid, bot))

def get_alias(bot, conv_id):
    """get the alias for the given conversation

    Args:
        bot: HangupsBot instance
        conv_id: string, Hangouts conversation identifier

    Returns:
        string, the alias for the conversation or None if no alias is set
    """
    for alias, conv_id_ in bot.memory['hoalias'].items():
        if conv_id_ == conv_id:
            return alias
    return None

def get_convid(bot, alias):
    """get the conversation of an alias

    Args:
        bot: HangupsBot instance
        alias: string, conversation alias

    Returns:
        string, the conversation identifier of the alias or None if no
            conversation was labeled with the alias
    """
    if alias in bot.memory['hoalias']:
        return bot.memory['hoalias'][alias]
    return None

def sethoalias(bot, event, *args):
    """set the alias for the current or given conversation

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple, a tuple of strings, additional words passed to the command

    Returns:
        string, the result wrapped in a text
    """
    if (len(args) not in (1, 2) or
            len(args) == 2 and args[1] not in bot.conversations):
        raise Help(_('Check Arguments'))

    alias_list = bot.memory['hoalias']
    newalias = args[0].lower()
    conv_id = event.conv_id if len(args) == 1 else args[1]

    oldalias = get_alias(bot, conv_id)
    if bot.memory.exists(['hoalias', oldalias]):
        alias_list.pop(oldalias)

    if newalias != 'none':
        alias_list[newalias] = conv_id
    bot.memory.save()

    if newalias == 'none':
        if conv_id == event.conv_id:
            return _('<i>HO alias deleted</i>')
        return _('<i>HO alias for</i>  {} <i>deleted</i>').format(conv_id)
    elif conv_id == event.conv_id:
        return _('<i>HO alias set to</i>  <b>{}</b>').format(newalias)

    return _('<i>HO alias for</i>  {} <i>is set to</i>  <b>{}</b>').format(
        conv_id, newalias)

def gethoalias(bot, event, *args):
    """get the alias for the current or given conversation

    Args:
        bot: HangupsBot instance
        event: event.ConversationEvent instance
        args: tuple, a tuple of strings, additional words passed to the command

    Returns:
        string, the result wrapped in a text or None if the event got redirected
    """
    if len(args) > 1:
        raise Help(_('Too many arguments!'))

    elif args and event.user_id.chat_id not in bot.config['admins']:
        raise Help(_('You are not authorized to do that!'))

    alias_list = bot.memory['hoalias']

    if args and args[0].lower() == 'all':
        text = [_('<u>List of HO Aliases</u>')]
        text.extend(['<b>{}</b> <i>({})</i>\n'.format(alias, id_)
                     for alias, id_ in alias_list.items()])
        return '\n'.join(text)

    conv_id = args[0] if args else event.conv_id
    alias = get_alias(bot, conv_id)

    if alias is None:
        if conv_id == event.conv_id:
            return _('<i>There is no alias set for this HO</i>')

        return _('<i>There is no alias set for the HO</i> %s') % conv_id

    elif conv_id == event.conv_id:
        return _('<i>Current HO alias is</i>  <b>%s</b>') % alias

    return _('<i>HO alias for</i>  %s <i>is</i>  <b>%s</b>') % (conv_id, alias)
