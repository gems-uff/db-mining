import re
import os
from util import VARIABLES

def tex_escape(text):
    """
        :param text: a plain text message
        :return: the message escaped to appear correctly in LaTeX
    """
    conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\^{}',
        '\\': r'\textbackslash{}',
        '<': r'\textless{}',
        '>': r'\textgreater{}',
    }
    regex = re.compile('|'.join(re.escape(key) for key in sorted(conv.keys(), key = lambda item: - len(item))))
    return regex.sub(lambda match: conv[match.group()], text)


def load_vars():
    data = {}
    if os.path.exists(VARIABLES):
        with open(VARIABLES, "r") as fil:
            for line in fil:
                line = line.strip()
                if line:
                    k, v = line.split(" = ")
                    data[k] = v
    return data

def var(key, value, template="{}"):
    result = template.format(value)
    latex_result = tex_escape(result)
    data = load_vars()
    data[key] = latex_result
    with open(VARIABLES, "w") as fil:
        fil.writelines(
            "{} = {}\n".format(k, v)
            for k, v in data.items()
        )
    return result

def relative_var(key, part, total, t1="{0:,}", t2="{0:.1%}"):
    relative_text = var(key, part / total, t2)
    part_text = var(key + "_total", part, t1)
    return "{} ({})".format(part_text, relative_text)
