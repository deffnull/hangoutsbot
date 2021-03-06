import time

import hangups
import plugins


def _initialise():
    plugins.register_handler(on_hangout_call, "call")

async def on_hangout_call(bot, event, command):
    if event.conv_event.event_type == hangups.HANGOUT_EVENT_TYPE_END:
        lastcall = bot.conversation_memory_get(event.conv_id, "lastcall")
        if lastcall:
            lastcaller = lastcall["caller"]
            since = int(time.time() - lastcall["timestamp"])


            if since < 120:
                humantime = "{} seconds".format(since)
            elif since < 7200:
                humantime = "{} minutes".format(since // 60)
            elif since < 172800:
                humantime = "{} hours".format(since // 3600)
            else:
                humantime = "{} days".format(since // 86400)

            if bot.conversations[event.conv_id]["type"] == "ONE_TO_ONE":
                # subsequent calls for a ONE_TO_ONE
                await bot.coro_send_message(
                    event.conv_id,
                    _("<b>It's been {} since the last call. Lonely? I can't "
                      "reply you as I don't have speech synthesis (or speech "
                      "recognition either!)</b>").format(humantime))

            else:
                # subsequent calls for a GROUP
                await bot.coro_send_message(
                    event.conv_id,
                    _("<b>It's been {} since the last call. The last caller was"
                      " <i>{}</i>.</b>").format(humantime, lastcaller))

        else:
            # first ever call for any conversation
            await bot.coro_send_message(
                event.conv_id, _("<b>No prizes for that call</b>"))

        bot.conversation_memory_set(
            event.conv_id, "lastcall", {"caller": event.user.full_name,
                                        "timestamp": time.time()})
