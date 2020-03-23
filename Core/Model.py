import collections

from Core.Side import Side
from TS.VectorModel import VectorModel
from Parsing.ParsePCTLformula import PCTLparser
import subprocess


class Model:
    def __init__(self, rules: set, init: collections.Counter, definitions: dict, params: set, bound: int):
        self.rules = rules
        self.init = init
        self.definitions = definitions
        self.params = params
        self.bound = bound
        self.all_rates = True

        # autocomplete
        self.atomic_signature, self.structure_signature = self.extract_signatures()

    def __eq__(self, other: 'Model') -> bool:
        return self.rules == other.rules and self.init == other.init and self.definitions == other.definitions

    def __str__(self):
        return "Model:\n" + "\n".join(map(str, self.rules)) + "\n\n" + str(self.init) + "\n\n" + str(self.definitions) \
               + "\n\n" + str(self.atomic_signature) + "\n" + str(self.structure_signature)

    def __repr__(self):
        return "#! rules\n" + "\n".join(map(str, self.rules)) + \
               "\n\n#! inits\n" + "\n".join([str(self.init[a]) + " " + str(a) for a in self.init]) + \
               "\n\n#! definitions\n" + "\n".join([str(p) + " = " + str(self.definitions[p]) for p in self.definitions])

    def extract_signatures(self):
        """
        Automatically creates signature from context of rules and initial state.
        Additionally it checks if all rules have a rate, sets all_rates to False otherwise.

        :return: created atomic and structure signatures
        """
        atomic_signature, structure_signature = dict(), dict()
        for rule in self.rules:
            if rule.rate is None:
                self.all_rates = False
            for agent in rule.agents:
                atomic_signature, structure_signature = agent.extend_signature(atomic_signature, structure_signature)
        for agent in list(self.init):
            atomic_signature, structure_signature = agent.extend_signature(atomic_signature, structure_signature)
        return atomic_signature, structure_signature

    def to_vector_model(self) -> VectorModel:
        """
        Creates vector representation of the model.

        First reactions are generated, then unique complexes are collected and finally both reactions and
        initial state are transformed to vector representation.

        THIS SHOULD BE DONE IN PARALLEL !!!

        :return: VectorModel representation of the model
        """
        reactions = set()
        unique_complexes = set()
        for rule in self.rules:
            reactions |= rule.create_reactions(self.atomic_signature, self.structure_signature)
        for reaction in reactions:
            unique_complexes |= set(reaction.lhs.to_counter()) | set(reaction.rhs.to_counter())
        unique_complexes |= set(self.init)
        ordering = tuple(sorted(unique_complexes))

        init = Side(self.init.elements()).to_vector(ordering)
        vector_reactions = set()
        for reaction in reactions:
            vector_reactions.add(reaction.to_vector(ordering, self.definitions))

        return VectorModel(vector_reactions, init, ordering, self.bound)

    def eliminate_redundant(self):
        pass

    def network_free_simulation(self, options) -> list:
        # for this we need to be able to apply Rule on State
        pass

    def PCTL_model_checking(self, PCTL_formula):
        ts = self.to_vector_model().generate_transition_system()
        formula = PCTLparser().parse(PCTL_formula)

        # generate labels and give them to save_storm
        APs = formula.get_APs()

        ts.save_to_STORM_explicit("explicit_transitions.tra", "explicit_labels.lab")
        '''
        command = "storm --explicit explicit_transitions.tra explicit_labels.lab --prop \"" + PCTL_formula + "\""
        os.system(command)
        '''

        out = subprocess.Popen(
            ['storm', '--explicit', 'explicit_transitions.tra', 'explicit_labels.lab', '--prop', formula.data],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = out.communicate()
        return stdout

    # check whether rate are "linear" -> create directly PRISM file
    # otherwise generate TS and use its explicit representation for Storm
    def PCTL_synthesis(self, PCTL_formula, region):
        ts = self.to_vector_model().generate_transition_system()
        formula = PCTLparser().parse(PCTL_formula)

        labels, prism_formulas = self.create_complex_labels(formula.get_complexes(), ts.ordering)
        formula = formula.replace_complexes(labels)

        ts.save_to_prism("prism-parametric.pm", self.bound, self.params, prism_formulas)

        # missing region and other stuff
        # storm-pars --prism parametric_die.pm --prop 'P<=0.5 [F s=7&d=1]'
        #            --region "0<=p<=1,0<=q<=0.5,0.1<=r<=0.3" --refine 0.01 10 --printfullresult
        out = subprocess.Popen(
            ['storm', '--prism', 'prism-parametric.pm', '--prop', formula.data],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout, stderr = out.communicate()
        return stdout

    def create_complex_labels(self, complexes: list, ordering: tuple):
        """
        Creates label for each unique Complex from Formula.
        This covers two cases - ground and abstract Complexes.
        For the abstract ones, a PRISM formula needs to be constructed as a sum
            of all compatible complexes.

        :param complexes: list of extracted complexes from Formula
        :param ordering: given complex ordering of TS
        :return: unique label for each Complex and list of PRISM formulas for abstract Complexes
        """
        labels = dict()
        prism_formulas = list()
        for complex in complexes:
            if complex in ordering:
                labels[complex] = complex.to_PRISM_code(ordering.index(complex))
            else:
                indices = complex.identify_compatible(ordering)
                id = "ABSTRACT_VAR_" + "".join(list(map(str, indices)))
                labels[complex] = id
                prism_formulas.append(id + " = " + "+".join(["VAR_{}".format(i) for i in indices]))
        return labels, prism_formulas
