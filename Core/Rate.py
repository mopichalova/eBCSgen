import numpy as np
import sympy
from lark import Transformer, Tree, Token
from sortedcontainers import SortedList

import TS.State

STATIC_MATH = """<kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply>{}</apply></math></kineticLaw>"""


class Rate:
    def __init__(self, expression):
        self.expression = expression

    def __eq__(self, other):
        return self.expression == other.expression

    def __repr__(self):
        return str(self)

    def __str__(self):
        return self.expression if type(self.expression) == str else "".join(tree_to_string(self.expression))

    def __hash__(self):
        return hash(str(self))

    def vectorize(self, ordering: SortedList, definitions: dict) -> list:
        """
        Converts all occurrences of Complexes (resp. sub trees named agent)
        with its vector representation. These are directly replaced within
        the tree expression.

        Moreover, in the process parameters are replaces with their values
        (if given).

        :param ordering: given SortedList of Complexes
        :param definitions: dict of (param_name, value)
        :return: list of transformed States (just for testing)
        """
        vec = Vectorizer(ordering, definitions)
        self.expression = vec.transform(self.expression)
        return vec.visited

    def evaluate(self, state) -> float:
        """
        Evaluates all occurrences of States to a float using Evaluater.
        It is done as intersection of particular state with given state
        and sum of resulting elements.

        If the result is nan, None is returned instead.

        :param state: given state
        :return: Sympy object for expression representation
        """
        evaluater = Evaluater(state)
        result = evaluater.transform(self.expression)

        try:
            value = sympy.sympify("".join(tree_to_string(result)), locals=evaluater.locals)
            if value == sympy.nan:
                return None
            return value
        except TypeError:
            return None

    def to_symbolic(self):
        """
        Translates rate from vector representation to symbolic one
        as a sum of particular components.
        e.g. [1, 0, 1] -> (x_0 + x_2)
        """
        transformer = SymbolicAgents()
        self.expression = transformer.transform(self.expression)

    def reduce_context(self) -> 'Rate':
        """
        Reduces context of all Complexes to minimum.

        :return: new Rate with reduced context
        """
        transformer = ContextReducer()
        expression = transformer.transform(self.expression)
        return Rate(expression)

    def get_params_and_agents(self):
        """
        Extracts all agents (Complex objects) and params (strings) used in the rate expression.

        :return: set of agents and params
        """
        transformer = Extractor()
        transformer.transform(self.expression)
        return transformer.agents, transformer.params

    def to_mathML(self):
        transformer = MathMLtransformer()
        expression = transformer.transform(self.expression)
        return STATIC_MATH.format(expression)

    def get_formula_in_list(self):
        return tree_to_string(self.expression)



# Transformers for Tree
class ContextReducer(Transformer):
    def agent(self, matches):
        return Tree("agent", [matches[0].reduce_context()])


class SymbolicAgents(Transformer):
    def agent(self, vector):
        vector = "(" + vector[0].to_ODE_string() + ")"
        return Tree("agent", [vector])


class Vectorizer(Transformer):
    def __init__(self, ordering, definitions):
        super(Vectorizer, self).__init__()
        self.ordering = ordering
        self.definitions = definitions
        self.visited = []

    def agent(self, complex):
        complex = complex[0]
        result = np.zeros(len(self.ordering))
        for i in range(len(self.ordering)):
            if complex.compatible(self.ordering[i]):
                result[i] = 1

        result = TS.State.State(result)
        self.visited.append(result)
        return Tree("agent", [result])

    def rate_agent(self, matches):
        return matches[1]

    def param(self, matches):
        return self.definitions.get(str(matches[0]), Tree("param", matches))


class Evaluater(Transformer):
    def __init__(self, state):
        super(Evaluater, self).__init__()
        self.state = state
        self.locals = dict()

    def agent(self, state):
        return sum(self.state * state[0])

    def param(self, matches):
        name = matches[0]
        self.locals[name] = sympy.Symbol(name)
        return name


class Extractor(Transformer):
    def __init__(self):
        super(Extractor, self).__init__()
        self.agents = set()
        self.params = set()

    def agent(self, matches):
        self.agents.add(matches[0])
        return Tree("agent", matches)

    def param(self, matches):
        self.params.add(matches[0])
        return Tree("param", matches)


class MathMLtransformer(Transformer):
    def __init__(self):
        super(MathMLtransformer, self).__init__()
        self.operators = {'STAR': 'times',
                          'PLUS': 'plus',
                          'MINUS': 'minus',
                          'POW': 'power',
                          'DIVIDE': 'divide'}

    def rate_agent(self, matches):
        return self.create_unary_item('ci', matches[1].children[0])

    def param(self, matches):
        return self.create_unary_item('ci', matches[0].value)

    def fun(self, matches):
        if len(matches) == 1:
            return self.process_leaf(matches[0])
        elif len(matches) == 3:
            if type(matches[0]) == Token:
                # ignore parentheses
                return matches[1]
            elif type(matches[1]) == Token:
                # binary operator
                second = self.process_leaf(matches[2]) if matches[1].type == 'POW' else matches[2]
                return self.create_binary_operator(matches[1].type, [matches[0], second])

        # this should never happen if the expression is parsed correctly
        raise Exception('Wrong syntax.')

    def rate(self, matches):
        if len(matches) == 3:
            # rational function
            return self.create_binary_operator('DIVIDE', [matches[0], matches[2]])
        else:
            return matches[0]

    def process_leaf(self, item):
        if type(item) == int or type(item) == float:
            # const
            return self.create_unary_item('cn', item)
        else:
            # param or agent
            return item

    def create_binary_operator(self, operator, items):
        return '<{0}>{1}</{0}>'.format(self.operators[operator], "".join(items))

    @staticmethod
    def create_unary_item(name, data):
        return '<{0}>{1}</{0}>'.format(name, data)


def tree_to_string(tree):
    if type(tree) == Tree:
        return sum(list(map(tree_to_string, tree.children)), [])
    else:
        return [str(tree)]
