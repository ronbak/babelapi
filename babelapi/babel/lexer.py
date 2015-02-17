import logging
import ply.lex as lex

class MultiToken(object):
    """Object used to monkeypatch ply.lex so that we can return multiple
    tokens from one lex operation."""
    def __init__(self, tokens):
        self.type = tokens[0].type
        self.tokens = tokens

# Represents a null value. We want to differentiate between the Python "None"
# and null in several places.
BabelNull = object()

class BabelLexer(object):
    """
    Lexer. Tokenizes babel files.
    """

    def __init__(self):
        self.lex = None
        self.tokens_queue = None
        self.cur_indent = None
        self._logger = logging.getLogger('babelapi.babel.lexer')
        self.last_token = None
        # [(character, line number), ...]
        self.errors = []

    def input(self, file_data, **kwargs):
        """
        Required by ply.yacc for this to quack (duck typing) like a ply lexer.

        :param str file_data: Contents of the file to lex.
        """
        self.lex = lex.lex(module=self, **kwargs)
        self.tokens_queue = []
        self.cur_indent = 0
        # Hack to avoid tokenization bugs caused by files that do not end in a
        # new line.
        self.lex.input(file_data + '\n')

    def token(self):
        """
        Returns the next LexToken. Returns None when all tokens have been
        exhausted.
        """

        if self.tokens_queue:
            self.last_token = self.tokens_queue.pop(0)
        else:
            r = self.lex.token()
            if isinstance(r, MultiToken):
                self.tokens_queue.extend(r.tokens)
                self.last_token = self.tokens_queue.pop(0)
            else:
                if r is None and self.cur_indent > 0:
                    if self.last_token and self.last_token.type not in ('NEWLINE', 'LINE'):
                        newline_token = self._create_token('NEWLINE', '\n', self.lex.lineno, self.lex.lexpos)
                        self.tokens_queue.append(newline_token)
                    dedent_count = self.cur_indent / 4
                    dedent_token = self._create_token('DEDENT', '\t', self.lex.lineno, self.lex.lexpos)
                    self.tokens_queue.extend([dedent_token] * dedent_count)

                    self.cur_indent = 0
                    self.last_token = self.tokens_queue.pop(0)
                else:
                    self.last_token = r
        return self.last_token

    def _create_token(self, token_type, value, lineno, lexpos):
        """
        Helper for creating ply.lex.LexToken objects. Unfortunately, LexToken
        does not have a constructor defined to make settings these values easy.
        """
        token = lex.LexToken()
        token.type = token_type
        token.value = value
        token.lineno = lineno
        token.lexpos = lexpos
        return token

    def test(self, data):
        """Logs all tokens for human inspection. Useful for debugging."""
        self.input(data)
        while True:
            token = self.token()
            if not token:
                break
            self._logger.debug('Token %r', token)

    # List of token names
    tokens = (
       'ID',
       'KEYWORD',
       'PATH',
       'PIPE',
       'DOT',
    )

    # Whitespace tokens
    tokens += (
        'DEDENT',
        'INDENT',
        'NEWLINE',
    )

    # Attribute lists, aliases
    tokens += (
        'COMMA',
        'EQ',
        'LPAR',
        'RPAR',
    )

    # Primitive types
    tokens += (
        'BOOLEAN',
        'FLOAT',
        'INTEGER',
        'NULL',
        'STRING',
    )

    tokens += (
        'ASTERIX',
        'Q',
    )

    # Regular expression rules for simple tokens
    t_DOT = r'\.'
    t_LPAR  = r'\('
    t_RPAR  = r'\)'
    t_EQ = r'='
    t_COMMA = r','
    t_PIPE = r'\|'
    t_ASTERIX = r'\*'
    t_Q = r'\?'

    KEYWORDS = [
        'alias',
        'deprecated',
        'doc',
        'example',
        'error',
        'extends',
        'attrs',
        'include',
        'namespace',
        'of',
        'pass',
        'request',
        'response',
        'route',
        'struct',
        'union',
    ]

    RESERVED = {
        'deprecated': 'DEPRECATED',
        'extends': 'EXTENDS',
        'attrs': 'ATTRS',
        'include': 'INCLUDE',
        'of': 'OF',
        'pass': 'PASS',
        'route': 'ROUTE',
        'struct': 'STRUCT',
        'union': 'UNION',
    }

    tokens += tuple(RESERVED.values())

    def t_BOOLEAN(self, token):
        r'\btrue\b|\bfalse\b'
        token.value = (token.value == 'true')
        return token

    def t_NULL(self, token):
        r'\bnull\b'
        token.value = BabelNull
        return token

    # No leading digits
    def t_ID(self, token):
        r'[a-zA-Z_][a-zA-Z0-9_-]*'
        if token.value in self.KEYWORDS:
            token.type = self.RESERVED.get(token.value, 'KEYWORD')
            return token
        else:
            return token

    def t_PATH(self, token):
        r'\/[/a-zA-Z0-9_-]*'
        return token

    def t_FLOAT(self, token):
        r'((\d*\.\d+)(E[\+-]?\d+)?|([1-9]\d*E[\+-]?\d+))'
        token.value = float(token.value)
        return token

    def t_INTEGER(self, token):
        r'\d+'
        token.value = int(token.value)
        return token

    # Read in a string while respecting the following escape sequences:
    # \", \\, \n, and \t.
    def t_STRING(self, t):
        r'\"([^\\"]|(\\.))*\"'
        escaped = 0
        t.lexer.lineno += t.value.count('\n')
        s = t.value[1:-1]
        new_str = ""
        for i in range(0, len(s)):
            c = s[i]
            if escaped:
                if c == 'n':
                    c = '\n'
                elif c == 't':
                    c = '\t'
                new_str += c
                escaped = 0
            else:
                if c == '\\':
                    escaped = 1
                else:
                    new_str += c
        # remove current indentation
        new_str = '\n'.join([line.replace(' ' * self.cur_indent, '')
                             for line in new_str.splitlines()])
        t.value = new_str
        return t

    # Ignore comments.
    # There are two types of comments.
    # 1. Comments that take up a full line. These lines are ignored entirely.
    # 2. Comments that come after tokens in the same line. These comments
    #    are ignored, but, we still need to emit a NEWLINE since this rule
    #    takes all trailing newlines.
    def t_comment(self, token):
        r'[#][^\n]*\n+'
        token.lexer.lineno += token.value.count('\n')
        # Scan backwards from the comment to the start of the line to figure
        # out which type of comment this is.
        i = token.lexpos - 1
        while i >= 0:
            if token.lexer.lexdata[i] == '\n':
                # Comment takes the full line so ignore entirely.
                return
            elif token.lexer.lexdata[i] != ' ':
                # Comment is only a partial line. Preserve newline token.
                newline_token = self._create_token('NEWLINE', '\n',
                    token.lineno, token.lexpos + len(token.value) - 1)
                newline_token.lexer = token.lexer
                # Call the newline handler since we may need to indent/dedent.
                return self.t_NEWLINE(newline_token)
            i -= 1

    # Define a rule so we can track line numbers
    def t_NEWLINE(self, newline_token):
        r'\n+'

        # Count lines
        newline_token.lexer.lineno += newline_token.value.count('\n')

        tokens = [newline_token]

        next_line_pos = newline_token.lexpos + len(newline_token.value)
        if next_line_pos == len(newline_token.lexer.lexdata):
            # Reached end of file
            return newline_token

        line = newline_token.lexer.lexdata[next_line_pos:].splitlines()[0]
        if not line:
            return newline_token

        indent = len(line) - len(line.lstrip())
        indent_spaces = indent - self.cur_indent
        if indent_spaces % 4 > 0:
            raise Exception('Indent was not divisible by 4.')

        indent_delta = indent_spaces / 4
        dent_type = 'INDENT' if indent_delta > 0 else 'DEDENT'
        dent_token = self._create_token(dent_type, '\t', newline_token.lineno + 1, next_line_pos)

        tokens.extend([dent_token] * abs(indent_delta))
        self.cur_indent = indent

        return MultiToken(tokens)

    # A string containing ignored characters (spaces and tabs)
    t_ignore = ' \t'

    # Error handling rule
    def t_error(self, token):
        self._logger.debug('Illegal character %r at line %d',
                           token.value[0], token.lexer.lineno)
        self.errors.append((token.value[0], token.lexer.lineno))
        token.lexer.skip(1)
