"""telepot message wrapper"""
__author__ = 'das7pad@outlook.com'

import logging

import telepot

from sync.event import SyncReply
from sync.user import SyncUser
from .user import User

logger = logging.getLogger(__name__)

class Message(dict):
    """parse the message once

    keep value accessing via dict

    Args:
        msg: dict from telepot
        tg_bot: TelegramBot instance
    """
    bot = None
    tg_bot = None
    _last_messages = {}

    def __init__(self, msg):
        super().__init__(msg)
        self.content_type, self.chat_type, chat_id = telepot.glance(msg)
        self.chat_id = str(chat_id)
        self.reply = (Message(msg['reply_to_message'])
                      if 'reply_to_message' in msg else None)
        self.user = User(self.tg_bot, msg)
        self.image_info = None
        self._set_content()
        self.add_message(self.chat_id, self.msg_id)

        base_path = ['telesync', 'chat_data', self.chat_id]
        user_path = base_path + ['user', self.user.usr_id]
        self.bot.memory.set_by_path(user_path, 1)
        self.bot.memory.get_by_path(base_path).update(msg['chat'])

    @property
    def edited(self):
        """Check whether the message is an update of a previous message

        Returns:
            boolean, True if the message is an update, otherwise False
        """
        return 'edit_date' in self

    @property
    def msg_id(self):
        """get the message identifier

        Returns:
            string, the unique identifier of the message
        """
        return str(self['message_id'])

    @classmethod
    def add_message(cls, chat_id, msg_id):
        """add a message id to the last message and delete old items

        Args:
            identifier: string, identifier for a chat
            msg_id: int or string, the unique id of the message
        """
        if chat_id in cls._last_messages:
            messages = cls._last_messages[chat_id]
        else:
            messages = cls._last_messages[chat_id] = []

        messages.append(int(msg_id or 0))
        messages.sort(reverse=True)
        for i in range(2 * cls.bot.config['sync_reply_spam_offset'],
                       len(messages)):
            messages.pop(i)

    def get_group_name(self):
        """get a configured chat title or the current title of the chat

        Returns:
            string: chat title of group/super/channel, or None
        """
        if self.chat_type in ['group', 'supergroup', 'channel']:
            name = self['chat']['title']
        else:
            name = _('DM - {}').format(self.user.full_name)
        # save the name but do not dump the memory explicit
        self.bot.memory.set_by_path(
            ['telesync', 'chat_data', self.chat_id, 'name'], name)
        return name

    async def get_reply(self):
        """check the reply for a hidden synced user and create the image

        Returns:
            a SyncReply instance with the user, text and image
        """
        if self.reply is None:
            return None
        separator = self.bot.config['sync_separator']
        if self.chat_type == 'channel':
            # do not display a user name
            self.reply.user.is_self = True
            user = self.reply.user
            text = self.reply.text
        elif (self.reply.user.usr_id == self.tg_bot.user.usr_id and
              separator in self.reply.text):
            # reply message has been synced, extract the user and text
            r_user, text = self.reply.text.split(separator, 1)
            # might be a reply as well
            r_user = r_user.rsplit('\n', 1)[-1]
            user = SyncUser(self.bot, identifier='telesync', user_name=r_user)
        else:
            user = self.reply.user
            text = self.reply.text

        if self.reply.image_info is not None:
            image = await self.tg_bot.get_image(*self.reply.image_info)
        else:
            image = None

        try:
            offset = self._last_messages[self.chat_id].index(
                int(self.reply.msg_id))
        except ValueError:
            offset = None

        return SyncReply(identifier='telesync', user=user, text=text,
                         offset=offset, image=image)

    def _set_content(self):
        """map content type to a propper message text and find images"""

        def _create_gmaps_url():
            """create Google Maps query from a location in the message

            Returns:
                string, a google maps link or .content_type or error
            """
            if not ('location' in self and
                    'latitude' in self['location'] and
                    'longitude' in self['location']):
                # missing requirement to create a valid maps link
                return self.content_type

            return 'https://maps.google.com/maps?q={lat},{lng}'.format(
                lat=self['location']['latitude'],
                lng=self['location']['longitude'])

        if self.content_type == 'text':
            self.text = self['text']
            return

        if self.content_type == 'photo':
            self.text = self.get('caption', '')
            sorted_photos = sorted(self['photo'], key=lambda k: k['width'])
            self.image_info = sorted_photos[- 1], 'photo'

        elif self.content_type == 'sticker':
            self.text = self["sticker"].get('emoji')
            self.image_info = self['sticker'], 'sticker'

        elif (self.content_type == 'document' and
              self['document'].get('mime_type') == 'video/mp4'
              and self['document'].get('file_size', 0) < 10000000):
            self.text = self.get('caption', '')
            self.image_info = self['document'], 'gif'

        elif (self.content_type == 'document' and
              self['document'].get('mime_type', '').startswith(('image/',
                                                                'video/'))):
            self.text = self.get('caption', '')
            extension = (self['document'].get('file_name') or
                         self['document']['mime_type']
                        ).rsplit('.', 1)[-1].rsplit('/', 1)[-1]

            type_ = ('photo' if 'image' in self['document']['mime_type']
                     else 'video')
            self.image_info = self['document'], type_, extension

        elif self.content_type == 'video':
            self.text = ''
            self.image_info = self['video'], 'video'

        elif self.content_type == 'location':
            self.text = _create_gmaps_url()

        else:
            self.text = '[{}]'.format(self.content_type)