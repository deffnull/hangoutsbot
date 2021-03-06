import re

import wikipedia

import plugins


def wiki(bot, event, *args):
    """lookup a term on Wikipedia"""

    term = " ".join(args)
    if not term:
        return

    try:
        page = wikipedia.page(term, auto_suggest=False)

        summary = page.summary.strip()
        summary = summary.replace('\r\n', '\n').replace('\r', '\n')
        summary = re.sub('\n+', "\n", summary).replace('\n', '\n\n')
        source = _('<i>source: <a href="{}">{}</a></i>').format(page.url, page.url)

        html_text = '<b>"{}"</b>\n\n{}\n\n{}'.format(term, summary, source)
    except wikipedia.exceptions.PageError:
        html_text = _("<i>no entry found for {}</i>").format(term)
    except wikipedia.exceptions.DisambiguationError as e:
        exception_text = str(e).strip().replace("\n", "\n")
        html_text = "<i>{}</i>".format(exception_text)

    return html_text


def _initialise():
    plugins.register_user_command(["wiki"])
