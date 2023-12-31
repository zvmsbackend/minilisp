import re
import code
import argparse
from functools import partial
from types import FunctionType
from typing import Iterator, Iterable

Pair = tuple['LispObject']
LispObject = str | int | Pair | None
Scope = tuple[dict[str, LispObject]] | None

current_procedure = None

class TailRecursion(BaseException): ...

def eval_lisp(syntax: LispObject, scope: Scope, tail=False) -> LispObject:
    match syntax:
        case int() as number:
            return number
        case str() as name:
            while scope is not None:
                top, scope = scope
                if name in top:
                    return top[name]
            return None
        case ['define', [str() as name, [value, None]]]:
            scope[0][name] = eval_lisp(value, scope)
            return None
        case ['if', [test, [body, [orelse, None]]]]:
            if eval_lisp(test, scope) is not None:
                return eval_lisp(body, scope, tail)
            return eval_lisp(orelse, scope, tail)
        case ['quote', [datum, None]]:
            return datum
        case ['let', [vars, body]]:
            if body is None:
                return None
            scope = {}, scope
            while vars is not None:
                match vars:
                    case [[str() as name, [value, None]], vars]:
                        scope[0][name] = eval_lisp(value, scope)
                    case _:
                        return None
            while body[1] is not None:
                expr, body = body
                eval_lisp(expr, scope)
            return eval_lisp(body[0], scope, tail)
        case ['lambda', [lambda_list, body]]:
            if body is None:
                def procedure(args): ...
            else:
                def procedure(args):
                    if tail and current_procedure is procedure:
                        raise TailRecursion
                    current_procedure = procedure
                    _scope = match_args(lambda_list, args, scope)
                    _body = body
                    while True:
                        while _body[1] is not None:
                            expr, _body = _body
                            eval_lisp(expr, _scope)
                        try:
                            return eval_lisp(_body[0], _scope, tail)
                        except TailRecursion as ex:
                            args = ex.__args__[0]
            return procedure
        case [fn, args]:
            acc = None
            while args is not None:
                arg, args = args
                acc = eval_lisp(arg, scope), acc
            accc = None
            while acc is not None:
                elt, acc = acc
                accc = elt, accc
            return eval_lisp(fn, scope)(accc)
        case _:
            return None

def match_args(lambda_list: Pair, args: Pair, scope: dict[str, LispObject]) -> Scope:
    scope = {}, scope
    while isinstance(lambda_list, tuple):
        name, lambda_list = lambda_list
        car, args = args
        scope[0][name] = car
    if isinstance(lambda_list, str):
        scope[0][name] = args
    return scope

def reverse(ls: Pair | None) -> Pair | None:
    acc = None
    while ls is not None:
        car, ls = ls
        acc = car, acc
    return acc

def repr_lisp(datum: LispObject) -> str:
    match datum:
        case FunctionType():
            return '<procedure>'
        case str():
            return datum
        case int():
            return str(datum)
        case None:
            return '()'
        case tuple():
            ls = []
            while isinstance(datum, tuple):
                car, datum = datum
                ls.append(repr_lisp(car))
            if isinstance(datum, str):
                ls.extend(['.', repr_lisp(datum)])
            return '(' + ' '.join(ls) + ')'
        
def iter_list(ls: Pair) -> Iterator[LispObject]:
    while ls is not None:
        car, ls = ls
        yield car

def product(it: Iterable):
    ret = 1
    for i in it:
        ret *= i
    return ret

load = lambda filename: (scope := ({}, base_scope)) and list(map(
    partial(eval_lisp, scope=scope), 
    Reader().read_many(
        open(filename, encoding='utf-8').read()
    )
)) or None

base_scope = {
    'car': lambda args: args[0][0],
    'cdr': lambda args: args[0][1],
    'cons': lambda args: (args[0], args[1][0]),
    '=': lambda args: 't' if args[0] is args[1][0] is None or isinstance(args[0], str) and isinstance(args[1][0], str) and args[0] == args[1][0] else None,
    'symbol?': lambda args: 't' if isinstance(args[0], str) else None,
    'load': lambda args: load(args[0]),
    'write': lambda args: print(repr_lisp(args[0])),
    'read': lambda args: Reader().read(input()),
    '+': lambda args: sum(iter_list(args)),
    '-': lambda args: -args[0] if args[1] is None else args[0] - sum(iter_list(args[1])),
    '*': lambda args: product(iter_list(args))
}, None

def lexer(code: str) -> Iterator[str]:
    scanner = re.compile(r'\(|\)|\'|\.|\s+|\d+|[^\(\)\'\.\s\d]+').scanner(code)
    for m in iter(scanner.match, None):
        if not m.group(0).isspace():
            yield m.group(0)

class Reader:
    def __init__(self) -> None:
        self.token = None
        self.next = None

    def read(self, code: str) -> LispObject:
        self.tokens = lexer(code)
        self._advance()
        return self.form()
    
    def read_many(self, code: str) -> Iterator[LispObject]:
        self.tokens = lexer(code)
        self._advance()
        return iter(self.form, None)
    
    def _advance(self):
        self.token, self.next = self.next, next(self.tokens, None)

    def _accept(self, token: str) -> bool:
        if self.next == token:
            self._advance()
            return True
        return False
    
    def _expect(self, token: str) -> None:
        if not self._accept(token):
            raise SyntaxError(f'expected {token}')
        
    def form(self) -> LispObject:
        if self._accept('('):
            acc = None
            while not self._accept(')'):
                if self._accept('.'):
                    accc = self.form()
                    while acc is not None:
                        car, acc = acc
                        accc = car, accc
                    self._expect(')')
                    return accc
                acc = self.form(), acc
            return reverse(acc)
        if self._accept('\''):
            return 'quote', (self.form(), None)
        self._advance()
        if self.token.isnumeric():
            return int(self.token)
        return self.token

class LispRepl(code.InteractiveConsole):
    def __init__(self) -> None:
        self.scope = {}, base_scope
        self.resetbuffer()
        self.filename = '<stdin>'

    def runcode(self, code: LispObject) -> None:
        try:
            print(repr_lisp(eval_lisp(code, self.scope, True)))
            return None
        except SystemExit:
            raise
        except:
            self.showtraceback()

    def compile(self, code: str, *_) -> LispObject:
        if code.strip() in ('exit', 'quit'):
            exit()
        return Reader().read(code)
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('filename', nargs='?')
    args = parser.parse_args()
    if args.filename:
        load(args.filename)
    else:
        LispRepl().interact()