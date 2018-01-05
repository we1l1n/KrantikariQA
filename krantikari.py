"""
    Author: geraltofrivia; saist1993
    The objective of this file to implement Krantikari QA.

    NOTE: A lot of code scavenged from preProcessing.py, some from parser.py


    Needs:
        - trained Keras model
        - working dbpedia interface
        - question
        - topic entity

    Pseudocode:
            +------------------------------------------------------------------------+
            |                  get a question                                        |
            |                       +                                                |
            |                       |                                                |
            |                       v                                                |
            |                  get entities                                          |
            |                   +         +                                          |
            |                   |         |                                          |
            |      1 entity  <--+         +-->   2 entities                          |
            |            +                              +                            |
            |            |                              |                            |
            |            v                              v                            |
            |      get subgraph                   get subgraph for  - S_e1           |
            |            +                            first entity                   |
            |            |                                  +                        |
            |            v                                  |                        |
            |    generate 1-hop paths                       v                        |
            |       ENT1 +/- R1                   get subgraph for  - S_e1           |
            |            |                           second entity                   |
            |            v                                  +                        |
            |     Pick top k options                        |                        |
            |            +                                  v                        |
            |            |                     Intersect them - S = S_e1 AND S_e2    |
            |            v                                  +                        |
            |    generate 2-hop paths                       |                        |
            |     ENT1 +/- R1 +/- R2                        v                        |
            |            |                       Generate paths in S like:           |
            |            v                       E1 +- R1 +- R2 +- E2                |
            |     Rank, pick top k                          +                        |
            |            +                                  |                        |
            |            |                                  v                        |
            |            |                         Rank, pick top k                  |
            |            |                                  +                        |
            |            |                                  |                        |
            |            |                                  |                        |
            |            |                                  |                        |
            |            +->  post ranking filters   <------+                        |
            |                        +                                               |
            |                        |                                               |
            |                        v                                               |
            |             convert core chain to sparql                               |
            |                        +                                               |
            |                        |                                               |
            |                        v                                               |
            |       detect if RDF:type constraints are needed                        |
            |                        +                                               |
            |                        |                                               |
            |                        v                                               |
            |                      ANSWER                                            |
            |                                                                        |
            +------------------------------------------------------------------------+


    Current Version: just one topic entity, multiple hops @TODO: Keep updating this.
"""

# Imports
import json
import pickle
import warnings
import editdistance
import numpy as np
from progressbar import ProgressBar

# Local file imports
from utils import model_interpreter
from utils import embeddings_interface
from utils import dbpedia_interface as db_interface
from utils import natural_language_utilities as nlutils

# Some MACROS
DEBUG = True
PATH_CHARS = ['+', '-', '/']
LCQUAD_DIR = './resources/data_set.json'
RESULTS_DIR = './resources/results.pickle'
QALD_DIR = './resources/qald-7-train-multilingual.json'
MODEL_DIR = 'data/training/multi_path_mini/model_00/model.h5'


short_forms = {
    'dbo:': 'http://dbpedia.org/ontology/',
    'res:': 'http://dbpedia.org/resource/',
    'rdf:': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dbp:': 'http://dbpedia.org/property/'
}

# Load a predicate blacklist from disk
PREDICATE_BLACKLIST = open('./resources/predicate.blacklist').read().split()


# Better warning formatting. Ignore.
def better_warning(message, category, filename, lineno, file=None, line=None):
    return ' %s:%s: %s:%s\n' % (filename, lineno, category.__name__, message)


class Krantikari:

    def __init__(self, _question, _entities, _dbpedia_interface, _model_interpreter, _qald=False):
        """
            This function inputs one question, and topic entities, and returns a SPARQL query (or s'thing else)

        :param _question: a string of question
        :param _entities: a list of strings (each being a URI)
        :return: SPARQL/CoreChain/Answers (and or)
        """
        # QA Specific Macros
        self.K_1HOP_GLOVE = 20
        self.K_1HOP_MODEL = 5
        self.K_2HOP_GLOVE = 10
        self.K_2HOP_MODEL = 5
        self.EMBEDDING = "glove"

        # Internalize args
        self.question = _question
        self.entities = _entities
        self.qald = _qald

        # Useful objects
        self.dbp = _dbpedia_interface
        self.model = _model_interpreter

        # @TODO: Catch answers once it returns something.
        self.runtime(self.question, self.entities, self.qald)

    @staticmethod
    def filter_predicates(_predicates, _use_blacklist=True, _only_dbo=False):
        """
            Function used to filter out predicates based on some logic
                - use a blacklist/whitelist @TODO: Make and plug one in.
                - only use dbo predicates, even.

        :param _predicates: A list of strings (uri of predicates)
        :param _use_blacklist: bool
        :param _only_dbo: bool
        :return: A list of strings (uri)
        """

        if _use_blacklist:
            _predicates = [x for x in _predicates
                           if x not in PREDICATE_BLACKLIST]

        if _only_dbo:
            _predicates = [x for x in _predicates
                           if x.startswith('http://dbpedia.org/ontology')
                           or x.startswith('dbo:')]

        # Filter out uniques
        _predicates = list(set(_predicates))

        return _predicates

    @staticmethod
    def choose_path_length(hop1_scores, hop2_scores):
        """
            Function chooses the most probable hop length given hop scores of both 1 and 2 hop scores
            Logic:
                Simply choose which of them have a better score
        :param hop1_scores:
        :param hop2_scores:
        :return: int: Score lenght
        """
        max_hop1_score = np.max(hop1_scores)
        max_hop2_score = np.max(hop2_scores)

        if max_hop1_score >= max_hop2_score:
            return 1
        else:
            return 2

    def convert_core_chain_to_sparql(self, _core_chain):  # @TODO
        pass

    def get_hop2_subgraph(self, _entity, _predicate, _right=True):
        """
            Function fetches the 2hop subgraph around this entity, and following this predicate
        :param _entity: str: URI of the entity around which we need the subgraph
        :param _predicate: str: URI of the predicate with which we curtail the 2hop graph (and get a tangible number of ops)
        :param _right: Boolean: True -> _predicate is on the right of entity (outgoing), else left (incoming)

        :return: List, List: ight (outgoing), left (incoming) preds
        """
        # Get the entities which will come out of _entity +/- _predicate chain
        intermediate_entities = self.dbp.get_entity(_entity, [_predicate], _right)

        # Filter out the literals, and keep uniques.
        intermediate_entities = list(set([x for x in intermediate_entities if x.startswith('http://dbpedia.org/resource')]))

        left_predicates, right_predicates = [], []  # Places to store data.

        for entity in intermediate_entities:
            temp_l, temp_r = self.dbp.get_properties(_uri=entity, label=False)
            left_predicates += temp_l
            right_predicates += temp_r

        return list(set(right_predicates)), list(set(left_predicates))

    def similar_predicates(self, _predicates, _return_indices=False, _k=5):
        """
            Function used to tokenize the question and compare the tokens with the predicates.
            Then their top k are selected.
        """
        # If there are no predicates
        if len(_predicates) == 0:
            return np.asarray([]) if _return_indices else []

        # Tokenize question
        qt = nlutils.tokenize(self.question, _remove_stopwords=False)

        # Vectorize question
        v_qt = np.mean(embeddings_interface.vectorize(qt, _embedding=self.EMBEDDING), axis=0)\

        # Declare a similarity array
        similarity_arr = np.zeros(len(_predicates))

        # Fill similarity array
        for i in range(len(_predicates)):
            p = _predicates[i]
            v_p = np.mean(embeddings_interface.vectorize(nlutils.tokenize(p), _embedding=self.EMBEDDING ), axis=0)

            # If either of them is a zero vector, the cosine is 0.
            if np.sum(v_p) == 0.0 or np.sum(v_qt) == 0.0:
                similarity_arr[i] = np.float64(0.0)
                continue

            # Cos Product
            similarity_arr[i] = np.dot(v_p, v_qt) / (np.linalg.norm(v_p) * np.linalg.norm(v_qt))

        # Find the best scoring values for every path
        # Sort ( best match score for each predicate) in descending order, and choose top k
        argmaxes = np.argsort(similarity_arr, axis=0)[::-1][:_k]

        if _return_indices:
            return argmaxes

        # Use this to choose from _predicates and return
        return [_predicates[i] for i in argmaxes]

    def runtime(self, _question, _entities, _qald=False):
        """
            This function inputs one question, and topic entities, and returns a SPARQL query (or s'thing else)

        :param _question: a string of question
        :param _entities: a list of strings (each being a URI)
        :param _qald: bool: Whether or not to use only dbo properties
        :return: SPARQL/CoreChain/Answers (and or)
        """
        # Two state fail macros
        NO_PATHS = False
        NO_PATHS_HOP2 = False

        # Vectorize the question
        id_q = embeddings_interface.vocabularize(nlutils.tokenize(_question), _embedding=self.EMBEDDING )

        # Algo differs based on whether there's one topic entity or two
        if len(_entities) == 1:

            # Get 1-hop subgraph around the entity
            right_properties, left_properties = self.dbp.get_properties(_uri=_entities[0], label=False)

            # @TODO: Use predicate whitelist/blacklist to trim this shit.
            right_properties = self.filter_predicates(right_properties, _use_blacklist=True, _only_dbo=_qald)
            left_properties = self.filter_predicates(left_properties, _use_blacklist=True, _only_dbo=_qald)

            # Get the surface forms of Entity and the predicates
            entity_sf = self.dbp.get_label(_resource_uri=_entities[0])
            right_properties_sf = [self.dbp.get_label(x) for x in right_properties]
            left_properties_sf = [self.dbp.get_label(x) for x in left_properties]

            # WORD-EMBEDDING FILTERING
            right_properties_filter_indices = self.similar_predicates(_predicates=right_properties_sf,
                                                                      _return_indices=True,
                                                                      _k=self.K_1HOP_GLOVE)
            left_properties_filter_indices = self.similar_predicates(_predicates=left_properties_sf,
                                                                     _return_indices=True,
                                                                     _k=self.K_1HOP_GLOVE)

            # Impose these indices to generate filtered predicate list.
            right_properties_filtered_sf = [right_properties_sf[i] for i in right_properties_filter_indices]
            left_properties_filtered_sf = [left_properties_sf[i] for i in left_properties_filter_indices]

            # Generate their URI counterparts
            right_properties_filtered_uri = [right_properties[i] for i in right_properties_filter_indices]
            left_properties_filtered_uri = [left_properties[i] for i in left_properties_filter_indices]

            # Generate 1-hop paths out of them
            paths_hop1_sf = [nlutils.tokenize(entity_sf) + ['+'] + nlutils.tokenize(_p)
                             for _p in right_properties_filtered_sf]
            paths_hop1_sf += [nlutils.tokenize(entity_sf) + ['-'] + nlutils.tokenize(_p)
                              for _p in left_properties_filtered_sf]

            # Create their corresponding paths but with URI.
            paths_hop1_uri = [[_entities[0], '+', _p] for _p in right_properties_filtered_uri]
            paths_hop1_uri += [[_entities[0], '-', _p] for _p in left_properties_filtered_uri]

            # Vectorize these paths.
            id_ps = [embeddings_interface.vocabularize(path, _embedding=self.EMBEDDING) for path in paths_hop1_sf]

            # MODEL FILTERING
            hop1_indices, hop1_scores = self.model.rank(_id_q=id_q,
                                                        _id_ps=id_ps,
                                                        _return_only_indices=False,
                                                        _k=self.K_1HOP_MODEL)

            # Impose indices on the paths.
            ranked_paths_hop1_sf = [paths_hop1_sf[i] for i in hop1_indices]
            ranked_paths_hop1_uri = [paths_hop1_uri[i] for i in hop1_indices]

            # if DEBUG:
            #     pprint(ranked_paths_hop1_sf)
            #     pprint(ranked_paths_hop1_uri)

            # Collect URI of predicates so filtered (for 2nd hop)
            left_properties_filtered, right_properties_filtered = [], []

            # Gather all the left and right predicates (from paths selected by the model)
            for i in hop1_indices:

                hop1_path = paths_hop1_sf[i]

                # See if it is from the left or right predicate set.
                if '-' in hop1_path:
                    # This belongs to the left pred list.
                    # Offset index to match to left_properties_filter_indices index.

                    i -= len(right_properties_filter_indices)
                    predicate = left_properties[left_properties_filter_indices[i]]
                    left_properties_filtered.append(predicate)

                else:
                    # This belongs to the right pred list.
                    # No offset needed

                    predicate = right_properties[right_properties_filter_indices[i]]
                    right_properties_filtered.append(predicate)

            """
                2 - Hop COMMENCES

                Note: Switching to LC-QuAD nomenclature hereon. Refer to /resources/nomenclature.png
            """
            e_in_in_to_e_in = {}
            e_in_to_e_in_out = {}
            e_out_to_e_out_out = {}
            e_out_in_to_e_out = {}

            for pred in right_properties_filtered:
                temp_r, temp_l = self.get_hop2_subgraph(_entity=_entities[0], _predicate=pred, _right=True)
                e_out_to_e_out_out[pred] = self.filter_predicates(temp_r, _use_blacklist=True, _only_dbo=_qald)
                e_out_in_to_e_out[pred] = self.filter_predicates(temp_l, _use_blacklist=True, _only_dbo=_qald)

            for pred in left_properties_filtered:
                temp_r, temp_l = self.get_hop2_subgraph(_entity=_entities[0], _predicate=pred, _right=False)
                e_in_to_e_in_out[pred] = self.filter_predicates(temp_r, _use_blacklist=True, _only_dbo=_qald)
                e_in_in_to_e_in[pred] = self.filter_predicates(temp_l, _use_blacklist=True, _only_dbo=_qald)

            # Get uniques
            # e_in_in_to_e_in = list(set(e_in_in_to_e_in))
            # e_in_to_e_in_out = list(set(e_in_to_e_in_out))
            # e_out_to_e_out_out = list(set(e_out_to_e_out_out))
            # e_out_in_to_e_out = list(set(e_out_in_to_e_out))

            # Predicates generated. @TODO: Use predicate whitelist/blacklist to trim this shit.

            # if DEBUG:
            #     print("HOP2 Subgraph")
            #     pprint(e_in_in_to_e_in)
            #     pprint(e_in_to_e_in_out)
            #     pprint(e_out_to_e_out_out)
            #     pprint(e_out_in_to_e_out)

            # Get their surface forms, maintain a key-value store
            sf_vocab = {}
            for key in e_in_in_to_e_in.keys():
                for uri in e_in_in_to_e_in[key]:
                    sf_vocab[uri] = self.dbp.get_label(uri)
            for key in e_in_to_e_in_out.keys():
                for uri in e_in_to_e_in_out[key]:
                    sf_vocab[uri] = self.dbp.get_label(uri)
            for key in e_out_to_e_out_out.keys():
                for uri in e_out_to_e_out_out[key]:
                    sf_vocab[uri] = self.dbp.get_label(uri)
            for key in e_out_in_to_e_out.keys():
                for uri in e_out_in_to_e_out[key]:
                    sf_vocab[uri] = self.dbp.get_label(uri)

            # Flatten the four kind of predicates, and use their surface forms.
            e_in_in_to_e_in_sf = [sf_vocab[x] for uris in e_in_in_to_e_in.values() for x in uris]
            e_in_to_e_in_out_sf = [sf_vocab[x] for uris in e_in_to_e_in_out.values() for x in uris]
            e_out_to_e_out_out_sf = [sf_vocab[x] for uris in e_out_to_e_out_out.values() for x in uris]
            e_out_in_to_e_out_sf = [sf_vocab[x] for uris in e_out_in_to_e_out.values() for x in uris]

            # WORD-EMBEDDING FILTERING
            e_in_in_to_e_in_filter_indices = self.similar_predicates(_predicates=e_in_in_to_e_in_sf,
                                                                     _return_indices=True,
                                                                     _k=self.K_2HOP_GLOVE)
            e_in_to_e_in_out_filter_indices = self.similar_predicates(_predicates=e_in_to_e_in_out_sf,
                                                                      _return_indices=True,
                                                                      _k=self.K_2HOP_GLOVE)
            e_out_to_e_out_out_filter_indices = self.similar_predicates(_predicates=e_out_to_e_out_out_sf,
                                                                        _return_indices=True,
                                                                        _k=self.K_2HOP_GLOVE)
            e_out_in_to_e_out_filter_indices = self.similar_predicates(_predicates=e_out_in_to_e_out_sf,
                                                                       _return_indices=True,
                                                                       _k=self.K_2HOP_GLOVE)

            # Impose these indices to generate filtered predicate list.
            e_in_in_to_e_in_filtered = [e_in_in_to_e_in_sf[i] for i in e_in_in_to_e_in_filter_indices]
            e_in_to_e_in_out_filtered = [e_in_to_e_in_out_sf[i] for i in e_in_to_e_in_out_filter_indices]
            e_out_to_e_out_out_filtered = [e_out_to_e_out_out_sf[i] for i in e_out_to_e_out_out_filter_indices]
            e_out_in_to_e_out_filtered = [e_out_in_to_e_out_sf[i] for i in e_out_in_to_e_out_filter_indices]

            # Use them to make a filtered dictionary of hop1: [hop2_filtered] pairs
            e_in_in_to_e_in_filtered_subgraph = {}
            for x in e_in_in_to_e_in_filtered:
                for uri in sf_vocab.keys():
                    if x == sf_vocab[uri]:

                        # That's the URI. Find it's 1-hop Pred.
                        for hop1 in e_in_in_to_e_in.keys():
                            if uri  in e_in_in_to_e_in[hop1]:

                                # Now we found a matching :sweat:
                                try:
                                    e_in_in_to_e_in_filtered_subgraph[hop1].append(uri)
                                except KeyError:
                                    e_in_in_to_e_in_filtered_subgraph[hop1] = [uri]

            e_in_to_e_in_out_filtered_subgraph = {}
            for x in e_in_to_e_in_out_filtered:
                for uri in sf_vocab.keys():
                    if x == sf_vocab[uri]:

                        # That's the URI. Find it's 1-hop Pred.
                        for hop1 in e_in_to_e_in_out.keys():
                            if uri in e_in_to_e_in_out[hop1]:

                                # Now we found a matching :sweat:
                                try:
                                    e_in_to_e_in_out_filtered_subgraph[hop1].append(uri)
                                except KeyError:
                                    e_in_to_e_in_out_filtered_subgraph[hop1] = [uri]

            e_out_to_e_out_out_filtered_subgraph = {}
            for x in e_out_to_e_out_out_filtered:
                for uri in sf_vocab.keys():
                    if x == sf_vocab[uri]:

                        # That's the URI. Find it's 1-hop Pred.
                        for hop1 in e_out_to_e_out_out.keys():
                            if uri in e_out_to_e_out_out[hop1]:

                                # Now we found a matching :sweat:
                                try:
                                    e_out_to_e_out_out_filtered_subgraph[hop1].append(uri)
                                except KeyError:
                                    e_out_to_e_out_out_filtered_subgraph[hop1] = [uri]

            e_out_in_to_e_out_filtered_subgraph = {}
            for x in e_out_in_to_e_out_filtered:
                for uri in sf_vocab.keys():
                    if x == sf_vocab[uri]:

                        # That's the URI. Find it's 1-hop Pred.
                        for hop1 in e_out_in_to_e_out.keys():
                            if uri in e_out_in_to_e_out[hop1]:

                                # Now we found a matching :sweat:
                                try:
                                    e_out_in_to_e_out_filtered_subgraph[hop1].append(uri)
                                except KeyError:
                                    e_out_in_to_e_out_filtered_subgraph[hop1] = [uri]

            # Generate 2-hop paths out of them.
            paths_hop2_log = []
            paths_hop2_sf = []
            paths_hop2_uri = []
            for key in e_in_in_to_e_in_filtered_subgraph.keys():
                for r2 in e_in_in_to_e_in_filtered_subgraph[key]:

                    path = nlutils.tokenize(entity_sf)                  \
                            + ['-'] + nlutils.tokenize(sf_vocab[key])   \
                            + ['-'] + nlutils.tokenize(sf_vocab[r2])
                    paths_hop2_sf.append(path)

                    path_uri = [_entities[0], '-', key, '-', r2]
                    paths_hop2_uri.append(path_uri)

            paths_hop2_log.append(len(paths_hop2_sf))
            for key in e_in_to_e_in_out_filtered_subgraph.keys():
                for r2 in e_in_to_e_in_out_filtered_subgraph[key]:

                    path = nlutils.tokenize(entity_sf)                  \
                            + ['-'] + nlutils.tokenize(sf_vocab[key])   \
                            + ['+'] + nlutils.tokenize(sf_vocab[r2])
                    paths_hop2_sf.append(path)

                    path_uri = [_entities[0], '-', key, '+', r2]
                    paths_hop2_uri.append(path_uri)

            paths_hop2_log.append(len(paths_hop2_sf))
            for key in e_out_to_e_out_out_filtered_subgraph.keys():
                for r2 in e_out_to_e_out_out_filtered_subgraph[key]:

                    path = nlutils.tokenize(entity_sf)                  \
                            + ['+'] + nlutils.tokenize(sf_vocab[key])   \
                            + ['+'] + nlutils.tokenize(sf_vocab[r2])
                    paths_hop2_sf.append(path)

                    path_uri = [_entities[0], '+', key, '+', r2]
                    paths_hop2_uri.append(path_uri)

            paths_hop2_log.append(len(paths_hop2_sf))
            for key in e_out_to_e_out_out_filtered_subgraph.keys():
                for r2 in e_out_to_e_out_out_filtered_subgraph[key]:

                    path = nlutils.tokenize(entity_sf)                  \
                            + ['+'] + nlutils.tokenize(sf_vocab[key])   \
                            + ['-'] + nlutils.tokenize(sf_vocab[r2])
                    paths_hop2_sf.append(path)

                    path_uri = [_entities[0], '+', key, '+', r2]
                    paths_hop2_uri.append(path_uri)

            paths_hop2_log.append(len(paths_hop2_sf))

            # Vectorize these paths
            id_ps = [embeddings_interface.vocabularize(path, _embedding=self.EMBEDDING) for path in paths_hop2_sf]

            if not len(id_ps) == 0:

                # MODEL FILTERING
                hop2_indices, hop2_scores = self.model.rank(_id_q=id_q,
                                                            _id_ps=id_ps,
                                                            _return_only_indices=False,
                                                            _k=self.K_2HOP_MODEL)

                # Impose indices
                ranked_paths_hop2_sf = [paths_hop2_sf[i] for i in hop2_indices]
                ranked_paths_hop2_uri = [paths_hop2_uri[i] for i in hop2_indices]

                self.path_length = self.choose_path_length(hop1_scores, hop2_scores)

                # @TODO: Merge hop1 and hop2 into one list and then rank/shortlist.

            else:

                # No paths generated at all.
                if DEBUG:
                    warnings.warn('No paths generated at the second hop. Question is \"%s\" %'
                                  % _question)

                NO_PATHS_HOP2 = True

            # Choose the best path length (1hop/2hop)
            if NO_PATHS_HOP2 is False: self.path_length = self.choose_path_length(hop1_scores, hop2_scores)
            else: self.path_length = 1

        if len(_entities) >= 2:
            self.best_path = 0  # @TODO: FIX THIS ONCE WE IMPLEMENT DIS!
            NO_PATHS = True
            pass

        # ###########
        # Paths have been generated and ranked.
        #   Now verify the state fail variables and decide what to do
        # ###########

        # If no paths generated, set best path to none
        if NO_PATHS:
            self.best_path = None
            return None

        # Choose best path
        if self.path_length == 1:
            self.best_path = ranked_paths_hop1_uri[np.argmax(hop1_scores)]
        elif self.path_length == 2:
            self.best_path = ranked_paths_hop2_uri[np.argmax(hop2_scores)]


def evaluate(_true, _predicted):
    """
       Fancier implementation of "are these corechains equal".
       Logic:
            Split the signs away from predicates in true paths

        Tests -
            - same path length?
            - same path pattern?
            - completely same path ?
            - completely same path (after abstracting out ontology/property conundrum)?
            - partially same path (entity, either predicate)?

    :return: Json object containing results of all the tests, including the true and predicted candidates for that test.
    """
    results = {}                               # Store different eval results here
    # If there are two or more entities, flail your arms around and run in circles
    if len(_true['entity']) >= 2:
        return 0

    # Parse the _true into something that resembles predicates
    true_path_parsed = [_true['entity'][0]]
    for token in _true['path']:
        if token.strip()[0] in PATH_CHARS:
            true_path_parsed.append(token.strip()[0])
            true_path_parsed.append(token.strip()[1:])
            continue
        true_path_parsed.append(token.strip())

    """
        Test 1:
            Check if the paths lengths is same or not
    """
    results['path-length'] = {'score': 1 if len(_predicted) == len(true_path_parsed) else 0,
                              'pred': len(_predicted),
                              'true': len(true_path_parsed)}

    """
        Test 2:
            Check the path patterns (edit distance)
    """
    # Check patterns of the paths
    true_path_pattern = ''.join(x for x in true_path_parsed if x in PATH_CHARS)
    pred_path_pattern = ''.join(x for x in _predicted if x in PATH_CHARS)
    results['path-pattern'] = {'score': editdistance.eval(true_path_pattern, pred_path_pattern),
                               'true': true_path_pattern,
                               'pred': pred_path_pattern}

    """
        Test 3:
            Check if the paths are exactly the same or not
    """
    results['perfect-match'] = {'score': 1 if _predicted == true_path_parsed else 0,
                                'pred': _predicted,
                                'true': true_path_parsed}

    """
        Test 4:
            Check if paths are the same after removing the prefixes.

            @TODO: Tokens with
    """
    true_path_unprefixed = [x.strip().split('/')[-1] for x in true_path_parsed]
    pred_path_unprefixed = [x.strip().split('/')[-1] for x in _predicted]
    results['perfect-match-unprefixed'] = {'score': 1 if true_path_unprefixed == pred_path_unprefixed else 0,
                                           'pred': pred_path_unprefixed,
                                           'true': true_path_unprefixed}

    return results


def get_triples(_sparql_query):
    """
        parses sparql query to return a set of triples
    """

    parsed = _sparql_query.split("{")
    parsed = [x.strip() for x in parsed]
    triples = parsed[1][:-1].strip()
    triples = triples.split(". ")
    triples = [x.strip() for x in triples]
    return triples


def parse_lcquad(_data):
    """
        Function to append useful information to LCQuAD json

    :param _data: JSON of LCQuAD
    :return: JSON of LCQuAD on steroids.
    """
    if _data[u"sparql_template_id"] in [1, 301, 401, 101]:  # :
        '''
            {
                u'_id': u'9a7523469c8c45b58ec65ed56af6e306',
                u'corrected_question': u'What are the schools whose city is Reading, Berkshire?',
                u'sparql_query': u' SELECT DISTINCT ?uri WHERE {?uri <http://dbpedia.org/ontology/city> <http://dbpedia.org/resource/Reading,_Berkshire> } ',
                u'sparql_template_id': 1,
                u'verbalized_question': u'What are the <schools> whose <city> is <Reading, Berkshire>?'
            }
        '''
        data_node = _data
        if ". }" not in _data[u'sparql_query']:
            _data[u'sparql_query'] = _data[u'sparql_query'].replace("}", ". }")
        triples = get_triples(_data[u'sparql_query'])
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[2][1:-1])
        data_node[u'path'] = ["-" + triples[0].split(" ")[1][1:-1]]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [301, 401]:
            data_node[u'constraints'] = {triples[1].split(" ")[0]: triples[1].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [401, 101]:
            data_node[u'constraints']['count'] = True
        return data_node

    elif _data[u"sparql_template_id"] in [2, 302, 402, 102]:
        '''
            {	u'_id': u'8216e5b6033a407191548689994aa32e',
                u'corrected_question': u'Name the municipality of Roberto Clemente Bridge ?',
                u'sparql_query': u' SELECT DISTINCT ?uri WHERE { <http://dbpedia.org/resource/Roberto_Clemente_Bridge> <http://dbpedia.org/ontology/municipality> ?uri } ',
                u'sparql_template_id': 2,
                u'verbalized_question': u'What is the <municipality> of Roberto Clemente Bridge ?'
            }
        '''
        # TODO: Verify the 302 template
        data_node = _data
        if ". }" not in _data[u'sparql_query']:
            _data[u'sparql_query'] = _data[u'sparql_query'].replace("}", ". }")
        triples = get_triples(_data[u'sparql_query'])
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[0][1:-1])
        data_node[u'path'] = ["+" + triples[0].split(" ")[1][1:-1]]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [302, 402]:
            data_node[u'constraints'] = {triples[1].split(" ")[0]: triples[1].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [402, 102]:
            data_node[u'constraints']['count'] = True
        return data_node

    elif _data[u"sparql_template_id"] in [3, 303, 309, 9, 403, 409, 103, 109]:
        '''
            {    u'_id': u'dad51bf9d0294cac99d176aba17c0241',
                 u'corrected_question': u'Name some leaders of the parent organisation of the Gestapo?',
                 u'sparql_query': u'SELECT DISTINCT ?uri WHERE { <http://dbpedia.org/resource/Gestapo> <http://dbpedia.org/ontology/parentOrganisation> ?x . ?x <http://dbpedia.org/ontology/leader> ?uri  . }',
                 u'sparql_template_id': 3,
                 u'verbalized_question': u'What is the <leader> of the <government agency> which is the <parent organisation> of <Gestapo> ?'}
        '''
        # pprint(node)
        data_node = _data
        triples = get_triples(_data[u'sparql_query'])
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[0][1:-1])
        rel2 = triples[1].split(" ")[1][1:-1]
        rel1 = triples[0].split(" ")[1][1:-1]
        data_node[u'path'] = ["+" + rel1, "+" + rel2]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [303, 309, 403, 409]:
            data_node[u'constraints'] = {triples[2].split(" ")[0]: triples[2].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [403, 409, 103, 109]:
            data_node[u'constraints']['count'] = True
        return data_node

    elif _data[u"sparql_template_id"] in [5, 305, 405, 105, 111]:
        '''
            >Verify this !!
            {
                u'_id': u'00a3465694634edc903510572f23b487',
                u'corrected_question': u'Which party has come in power in Mumbai North?',
                u'sparql_query': u'SELECT DISTINCT ?uri WHERE { ?x <http://dbpedia.org/property/constituency> <http://dbpedia.org/resource/Mumbai_North_(Lok_Sabha_constituency)> . ?x <http://dbpedia.org/ontology/party> ?uri  . }',
                u'sparql_template_id': 5,
                u'verbalized_question': u'What is the <party> of the <office holders> whose <constituency> is <Mumbai North (Lok Sabha constituency)>?'
            }
        '''
        # pprint(node)
        data_node = _data
        triples = get_triples(_data[u'sparql_query'])
        rel1 = triples[0].split(" ")[1][1:-1]
        rel2 = triples[1].split(" ")[1][1:-1]
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[2][1:-1])
        data_node[u'path'] = ["-" + rel1, "+" + rel2]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [305, 405]:
            data_node[u'constraints'] = {triples[2].split(" ")[0]: triples[2].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [105, 405, 111]:
            data_node[u'constraints']['count'] = True
        return data_node

    elif _data[u'sparql_template_id'] in [6, 306, 406, 106]:
        '''
            {
                u'_id': u'd3695db03a5e45ae8906a2527508e7c5',
                u'corrected_question': u'Who have done their PhDs under a National Medal of Science winner?',
                u'sparql_query': u'SELECT DISTINCT ?uri WHERE { ?x <http://dbpedia.org/property/prizes> <http://dbpedia.org/resource/National_Medal_of_Science> . ?uri <http://dbpedia.org/property/doctoralAdvisor> ?x  . }',
                u'sparql_template_id': 6,
                u'verbalized_question': u"What are the <scientists> whose <advisor>'s <prizes> is <National Medal of Science>?"
            }
        '''
        # pprint(node)
        data_node = _data
        triples = get_triples(_data[u'sparql_query'])
        rel1 = triples[0].split(" ")[1][1:-1]
        rel2 = triples[1].split(" ")[1][1:-1]
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[2][1:-1])
        data_node[u'path'] = ["-" + rel1, "-" + rel2]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [306, 406]:
            data_node[u'constraints'] = {triples[2].split(" ")[0]: triples[2].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [406, 106]:
            data_node[u'constraints']['count'] = True
        return data_node

    elif _data[u'sparql_template_id'] in [7, 8, 307, 308, 407, 408, 107, 108]:
        '''
            {
                u'_id': u'6ff03a568e2e4105b491ab1c1411c1ab',
                u'corrected_question': u'What tv series can be said to be related to the sarah jane adventure and dr who confidential?',
                u'sparql_query': u'SELECT DISTINCT ?uri WHERE { ?uri <http://dbpedia.org/ontology/related> <http://dbpedia.org/resource/The_Sarah_Jane_Adventures> . ?uri <http://dbpedia.org/ontology/related> <http://dbpedia.org/resource/Doctor_Who_Confidential> . }',
                u'sparql_template_id': 7,
                u'verbalized_question': u'What is the <television show> whose <relateds> are <The Sarah Jane Adventures> and <Doctor Who Confidential>?'
             }
        '''
        # pprint(node)
        data_node = _data
        triples = get_triples(_data[u'sparql_query'])
        rel1 = triples[0].split(" ")[1][1:-1]
        rel2 = triples[1].split(" ")[1][1:-1]
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[2][1:-1])
        data_node[u'entity'].append(triples[1].split(" ")[2][1:-1])
        data_node[u'path'] = ["-" + rel1, "+" + rel2]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [307, 407, 308, 408]:
            data_node[u'constraints'] = {triples[2].split(" ")[0]: triples[2].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [407, 107, 408, 108]:
            data_node[u'constraints']['count'] = True
        return data_node

    elif _data[u'sparql_template_id'] in [15, 16, 315, 316, 415, 416, 115, 116]:
        '''
            {
                u'_id': u'6ff03a568e2e4105b491ab1c1411c1ab',
                u'corrected_question': u'What tv series can be said to be related to the sarah jane adventure and dr who confidential?',
                u'sparql_query': u'SELECT DISTINCT ?uri WHERE { ?uri <http://dbpedia.org/ontology/related> <http://dbpedia.org/resource/The_Sarah_Jane_Adventures> . ?uri <http://dbpedia.org/ontology/related> <http://dbpedia.org/resource/Doctor_Who_Confidential> . }',
                u'sparql_template_id': 7,
                u'verbalized_question': u'What is the <television show> whose <relateds> are <The Sarah Jane Adventures> and <Doctor Who Confidential>?'
             }
        '''
        data_node = _data
        _data[u'sparql_query'] = _data[u'sparql_query'].replace('uri}', 'uri . }')
        triples = get_triples(_data[u'sparql_query'])
        rel1 = triples[0].split(" ")[1][1:-1]
        rel2 = triples[1].split(" ")[1][1:-1]
        data_node[u'entity'] = []
        data_node[u'entity'].append(triples[0].split(" ")[0][1:-1])
        data_node[u'entity'].append(triples[1].split(" ")[0][1:-1])
        data_node[u'path'] = ["+" + rel1, "+" + rel2]
        data_node[u'constraints'] = {}
        if _data[u"sparql_template_id"] in [315, 415, 316, 416]:
            data_node[u'constraints'] = {triples[2].split(" ")[0]: triples[2].split(" ")[2][1:-1]}
        if _data[u"sparql_template_id"] in [415, 115, 416, 116]:
            data_node[u'constraints']['count'] = True
        return data_node


def parse_qald(_data):

    node = _data
    sparql_query = node['query']['sparql']	#The sparql query of the question
    triples = get_triples(sparql_query) #this will return the all the triples present in the SPARQL query
    triples = [chain.replace(' .','').strip() for chain in triples]	#remove the . from each line of the SPARQL query
    parsed_response = {}
    if len(triples) == 1:
        id = 1 #represents a single triple query
        if "@en" in triples[0]:
            #it has literal. Need to be handeled differently
            return None
        else:
            try:
                parsed_response[u'corrected_question'] = node['question'][0]['string']
                parsed_response[u'sparql_query'] = sparql_query
                parsed_response[u'constraints'] = {}
                core_chains = triples[0].split(' ')	#split by space to get individual element of chain
                core_chains =[i.strip() for i in core_chains]		#clean up the extra space
                for i in xrange(len(core_chains)):	#replace dbo: with http://dbpedia.org/ontology/ so on and so forth
                    for keys in short_forms:
                        if keys in core_chains[i]:
                            core_chains[i] = core_chains[i].replace(keys,short_forms[keys])
                if "?" in core_chains[0]:
                    # implies that the first position is a variable
                    # check for '<', '>'
                    parsed_response[u'entity'] = [nlutils.checker(core_chains[2])]
                    parsed_response[u'path'] = ['-'+nlutils.checker(core_chains[1])]
                else:
                    #implies third position is a variable
                    parsed_response[u'entity'] = [nlutils.checker(core_chains[0])]
                    parsed_response[u'path'] = ['+' + nlutils.checker(core_chains[1])]
            except:
                return None
    else:
        return None
    return  parsed_response


def run_lcquad():
    """
        Function to run the entire script on LC-QuAD, the lord of all datasets.
        - Load dataset
        - Parse it
        - Find length of all paths
        - Give every question to Krantikari,
        - Compare lengths.
        - Store results in an array.

    :return:
    """
    results = []

    # Create a DBpedia object.
    dbp = db_interface.DBPedia(_verbose=True, caching=True)  # Summon a DBpedia interface

    # Create a model interpreter.
    model = model_interpreter.ModelInterpreter()  # Model interpreter to be used for ranking

    # Load LC-QuAD
    dataset = json.load(open(LCQUAD_DIR))

    progbar = ProgressBar()
    iterator = progbar(dataset)

    # Parse it
    for x in iterator:
        parsed_data = parse_lcquad(x)

        if not parsed_data:
            continue

        # Get Needed data
        q = parsed_data[u'corrected_question']
        e = parsed_data[u'entity']

        if len(e) > 1:
            # results.append([0, 0])
            continue

        qa = Krantikari(_question=q, _entities=e, _model_interpreter=model, _dbpedia_interface=dbp)
        results.append(evaluate(parsed_data, qa.best_path))

    # I don't know what to do of results. So just pickle shit
    pickle.dump(results, open(RESULTS_DIR, 'w+'))


def run_qald():

    results = []

    # Create a DBpedia object.
    dbp = db_interface.DBPedia(_verbose=True, caching=True)  # Summon a DBpedia interface

    # Create a model interpreter.
    model = model_interpreter.ModelInterpreter()  # Model interpreter to be used for ranking

    # Load QALD
    dataset = json.load(open(QALD_DIR))

    # Basic Pre-Processing
    dataset = dataset['questions']
    for i in range(len(dataset)):
        dataset[i]['query']['sparql'] = dataset[i]['query']['sparql'].replace('.\n', '. ')

    progbar = ProgressBar()
    iterator = progbar(dataset[:5])

    # Parse it
    for node in iterator:
        parsed_data = parse_qald(node)

        if not parsed_data:
            continue

        # Get Needed data
        q = parsed_data[u'corrected_question']
        e = parsed_data[u'entity']

        if len(e) > 1:
            results.append([0, 0])
            continue

        qa = Krantikari(_question=q, _entities=e, _model_interpreter=model, _dbpedia_interface=dbp, _qald=True)
        results.append(evaluate(parsed_data, qa.best_path))

    # I don't know what to do of results. So just pickle shit
    pickle.dump(results, open(RESULTS_DIR, 'w+'))


if __name__ == "__main__":
    # """
    #     TEST1 : Accuracy of similar_predicates
    # """
    # _question = 'Who is the president of Nicaragua ?'
    # p = ['abstract', 'motto', 'population total', 'official language', 'legislature', 'lower house', 'president',
    #      'leader', 'prime minister']
    # _entities = ['http://dbpedia.org/resource/Nicaragua']
    #
    # # Create a DBpedia object.
    # dbp = db_interface.DBPedia(_verbose=True, caching=True)  # Summon a DBpedia interface
    #
    # # Create a model interpreter.
    # model = model_interpreter.ModelInterpreter()  # Model interpreter to be used for ranking
    #
    # qa = Krantikari(_question, _entities,
    #                 _dbpedia_interface=dbp,
    #                 _model_interpreter=model,
    #                 _return_core_chains=True,
    #                 _return_answers=False)
    #
    # print(qa.path_length)

    """
        TEST 2 : Check LCQuAD Parser
    """
    run_lcquad()

