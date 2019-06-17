# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from enum import Enum
import logging

from pytorch_pretrained_bert.tokenization import BertTokenizer

import torch
from torch.utils.data import (
    DataLoader,
    RandomSampler,
    SequentialSampler,
    TensorDataset,
)
from torch.utils.data.distributed import DistributedSampler

module_logger = logging.getLogger(__name__)

# Max supported sequence length
BERT_MAX_LEN = 512


class Language(Enum):
    """An enumeration of the supported languages."""

    ENGLISH = "bert-base-uncased"
    ENGLISHCASED = "bert-base-cased"
    ENGLISHLARGE = "bert-large-uncased"
    ENGLISHLARGECASED = "bert-large-cased"
    CHINESE = "bert-base-chinese"
    MULTILINGUAL = "bert-base-multilingual-cased"


class Tokenizer(object):
    def __init__(
        self, language=Language.ENGLISH, to_lower=False, cache_dir="."
    ):
        """Initializes the underlying pretrained BERT tokenizer.
        Args:
            language (Language, optional): The pretrained model's language.
                                           Defaults to Language.ENGLISH.
            to_lower (bool, optional): Whether to downcast inputs to lower.
                Defaults to False.
            cache_dir (str, optional): Location of BERT's cache directory.
                Defaults to ".".
        """
        self.tokenizer = BertTokenizer.from_pretrained(
            language.value, do_lower_case=to_lower, cache_dir=cache_dir
        )
        self.language = language

    def tokenize(self, text):
        """Tokenizes a list of documents using a BERT tokenizer
        Args:
            text (list(str)): list of text documents.
        Returns:
            [list(str)]: list of token lists.
        """
        return [self.tokenizer.tokenize(x) for x in text]

    def preprocess_classification_tokens(self, tokens, max_len=BERT_MAX_LEN):
        """Preprocessing of input tokens:
            - add BERT sentence markers ([CLS] and [SEP])
            - map tokens to indices
            - pad and truncate sequences
            - create an input_mask
        Args:
            tokens (list): List of tokens to preprocess.
            max_len (int, optional): Maximum number of tokens
                            (documents will be truncated or padded).
                            Defaults to 512.
        Returns:
            list of preprocesssed token lists
            list of input mask lists
        """
        if max_len > BERT_MAX_LEN:
            module_logger.info(
                "setting max_len to max allowed tokens: {}".format(BERT_MAX_LEN)
            )
            max_len = BERT_MAX_LEN

        # truncate and add BERT sentence markers
        tokens = [["[CLS]"] + x[0 : max_len - 2] + ["[SEP]"] for x in tokens]
        # convert tokens to indices
        tokens = [self.tokenizer.convert_tokens_to_ids(x) for x in tokens]
        # pad sequence
        tokens = [x + [0] * (max_len - len(x)) for x in tokens]
        # create input mask
        input_mask = [[min(1, x) for x in y] for y in tokens]
        return tokens, input_mask

    def preprocess_ner_tokens(
        self,
        text,
        max_len=BERT_MAX_LEN,
        labels=None,
        label_map=None,
        trailing_piece_tag="X",
    ):
        """
        Preprocesses input text, involving the following steps
            0. Tokenize input text.
            1. Convert string tokens to token ids.
            2. Convert input labels to label ids, if labels and label_map are
                provided.
            3. If a word is tokenized into multiple pieces of tokens by the
                WordPiece tokenizer, label the extra tokens with
                trailing_piece_tag.
            4. Pad or truncate input text according to max_seq_length
            5. Create input_mask for masking out padded tokens.

        Args:
            text (list): List of input sentences/paragraphs.
            max_len (int, optional): Maximum length of the list of
                tokens. Lists longer than this are truncated and shorter
                ones are padded with "O"s. Default value is BERT_MAX_LEN=512.
            labels (list, optional): List of token label lists. Default
                value is None.
            label_map (dict, optional): Dictionary for mapping original token
                labels (which may be string type) to integers. Default value
                is None.
            trailing_piece_tag (str, optional): Tag used to label trailing
                word pieces. For example, "playing" is broken into "play"
                and "##ing", "play" preserves its original label and "##ing"
                is labeled as trailing_piece_tag. Default value is "X".

        Returns:
            tuple: A tuple containing the following three or four lists.
                1. input_ids_all: List of lists. Each sublist contains
                    numerical values, i.e. token ids, corresponding to the
                    tokens in the input text data.
                2. input_mask_all: List of lists. Each sublist
                    contains the attention mask of the input token id list,
                    1 for input tokens and 0 for padded tokens, so that
                    padded tokens are not attended to.
                3. trailing_token_mask: List of lists. Each sublist is
                    a boolean list, True for the first word piece of each
                    original word, False for the trailing word pieces,
                    e.g. "##ing". This mask is useful for removing the
                    predictions on trailing word pieces, so that each
                    original word in the input text has a unique predicted
                    label.
                4. label_ids_all: List of lists of numerical labels,
                    each sublist contains token labels of a input
                    sentence/paragraph, if labels is provided.
        """
        # TODO can this return a namedtuple to support returned_obj.label_ids_all
        # https://pymotw.com/2/collections/namedtuple.html and avoid returned_obj[3]
        if max_len > BERT_MAX_LEN:
            max_len = BERT_MAX_LEN
            logger.warning(
                "set max_len to max allowed tokens: {}".format(max_len)
            )

        #  Must be called before setting label to the default value
        label_available = labels is not None

        # create an artificial label list for creating trailing token mask
        labels = labels if labels is not None else ["O"] * len(text)

        input_ids_all = []
        input_mask_all = []
        label_ids_all = []
        trailing_token_mask_all = []
        for t, t_labels in zip(text, labels):
            new_labels = []
            tokens = []
            for word, tag in zip(t.split(), t_labels):
                sub_words = self.tokenizer.tokenize(word)
                for count, sub_word in enumerate(sub_words):
                    if count > 0:
                        tag = trailing_piece_tag
                    new_labels.append(tag)
                    tokens.append(sub_word)

            if len(tokens) > max_len:
                tokens = tokens[:max_len]
                new_labels = new_labels[:max_len]

            input_ids = self.tokenizer.convert_tokens_to_ids(tokens)

            # The mask has 1 for real tokens and 0 for padding tokens.
            # Only real tokens are attended to.
            input_mask = [1.0] * len(input_ids)

            # Zero-pad up to the max sequence length.
            padding = [0.0] * (max_len - len(input_ids))
            label_padding = ["O"] * (max_len - len(input_ids))

            input_ids += padding
            input_mask += padding
            new_labels += label_padding

            trailing_token_mask_all.append(
                [label != trailing_piece_tag for label in new_labels]
            )

            if label_map:
                label_ids = [label_map[label] for label in new_labels]
            else:
                label_ids = new_labels

            input_ids_all.append(input_ids)
            input_mask_all.append(input_mask)
            label_ids_all.append(label_ids)

        if label_available:
            return (
                input_ids_all,
                input_mask_all,
                trailing_token_mask_all,
                label_ids_all,
            )
        else:
            return input_ids_all, input_mask_all, trailing_token_mask_all


def create_data_loader(
    input_ids,
    input_mask,
    label_ids=None,
    sample_method="random",
    batch_size=32,
):
    """
    Create a dataloader for sampling and serving data batches.
    Args:
        input_ids (list): List of lists. Each sublist contains numerical
            values, i.e. token ids, corresponding to the tokens in the input
            text data.
        input_mask (list): List of lists. Each sublist contains the attention
            mask of the input token id list, 1 for input tokens and 0 for
            padded tokens, so that padded tokens are not attended to.
        label_ids (list, optional): List of lists of numerical labels,
            each sublist contains token labels of a input
            sentence/paragraph. Default value is None.
        sample_method (str, optional): Order of data sampling. Accepted
            values are "random", "sequential" and "distributed". Default
            value is "random".
        batch_size (int, optional): Number of samples used in each training
            iteration. Default value is 32.

    Returns:
        DataLoader: A Pytorch Dataloader containing the input_ids tensor,
            input_mask tensor, and label_ids (if provided) tensor.

    """
    input_ids_tensor = torch.tensor(input_ids, dtype=torch.long)
    input_mask_tensor = torch.tensor(input_mask, dtype=torch.long)

    if label_ids:
        label_ids_tensor = torch.tensor(label_ids, dtype=torch.long)
        tensor_data = TensorDataset(
            input_ids_tensor, input_mask_tensor, label_ids_tensor
        )
    else:
        tensor_data = TensorDataset(input_ids_tensor, input_mask_tensor)

    name_to_sampler_class = {
        "random": RandomSampler,
        "sequential": SequentialSampler,
        "distributed": DistributedSampler
    }
    try:
        sampler_class = name_to_sampler_class[sample_method]
        sampler = sampler_class(tensor_data)
    except KeyError:
        raise ValueError(
            "Invalid sample_method value: {}, accepted values are: "
            "random, sequential, and distributed".format(sample_method)
        )

    return DataLoader(tensor_data, sampler=sampler, batch_size=batch_size)


class BERTModelWrapper(object):
      """BERT-based model"""

    def __init__(self, language=Language.ENGLISH, num_labels=2, cache_dir="."):
        """Initializes the underlying pretrained model.
        Args:
            language (Language, optional): The pretrained model's language.
                                           Defaults to Language.ENGLISH.
            num_labels (int, optional): The number of unique labels in the
                training data. Defaults to 2.
            cache_dir (str, optional): Location of BERT's cache directory.
                Defaults to ".".
        """
        if num_labels < 2:
            raise ValueError("Number of labels should be at least 2. Was {}.".format(num_labels))

        self.language = language
        self.num_labels = num_labels
        self.cache_dir = cache_dir
        self.model = self._load_model()

    def _load_model(self):
        """Called to initialize the BERT pretrained model."""
        raise NotImplementedError("BERT model wrappers must override _load_model")
