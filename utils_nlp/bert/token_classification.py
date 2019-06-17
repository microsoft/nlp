# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

# This script reuses some code from
# https://github.com/huggingface/pytorch-pretrained-BERT/blob/master/examples
# /run_classifier.py

import numpy as np
from tqdm import tqdm, trange

from pytorch_pretrained_bert.optimization import BertAdam
from pytorch_pretrained_bert.modeling import BertForTokenClassification

import torch
import torch.nn as nn

from .common import Language, create_data_loader, BERTModelWrapper

from utils_nlp.pytorch.device_utils import get_device, move_to_device


# TODO shared API with sequence classification but no shared code?
class BERTTokenClassifier(BERTModelWrapper):
    """BERT-based token classifier."""

    def _load_model(self):
        """Loads the classifier and the underlying pre-trained model.
        Returns:
            Model: A BERT based PyTorch Token Classifier.
        """
        return BertForTokenClassification.from_pretrained(
            language.value, cache_dir=cache_dir, num_labels=num_labels
        )

    def _get_optimizer(
        self, learning_rate, num_train_optimization_steps, warmup_proportion
    ):
        """
        Initializes the optimizer and configure parameters to apply weight
        decay on.
        """
        param_optimizer = list(self.model.named_parameters())
        no_decay_params = ["bias", "LayerNorm.bias", "LayerNorm.weight"]
        params_weight_decay = 0.01
        optimizer_grouped_parameters = [
            {
                "params": [
                    p
                    for n, p in param_optimizer
                    if not any(nd in n for nd in no_decay_params)
                ],
                "weight_decay": params_weight_decay,
            },
            {
                "params": [
                    p
                    for n, p in param_optimizer
                    if any(nd in n for nd in no_decay_params)
                ],
                "weight_decay": 0.0,
            },
        ]

        if warmup_proportion is None:
            optimizer = BertAdam(
                optimizer_grouped_parameters, lr=learning_rate
            )
        else:
            optimizer = BertAdam(
                optimizer_grouped_parameters,
                lr=learning_rate,
                t_total=num_train_optimization_steps,
                warmup=warmup_proportion,
            )

        return optimizer

    def fit(
        self,
        token_ids,
        input_mask,
        labels,
        num_gpus=None,
        num_epochs=1,
        batch_size=32,
        learning_rate=2e-5,
        warmup_proportion=None,
    ):
        """
        Fine-tunes the BERT classifier using the given training data.

        Args:
            token_ids (list): List of lists. Each sublist contains
                numerical token ids corresponding to the tokens in the input
                text data.
            input_mask (list): List of lists. Each sublist contains
                the attention mask of the input token id list. 1 for input
                tokens and 0 for padded tokens, so that padded tokens are
                not attended to.
            labels (list): List of lists, each sublist contains numerical
                token labels of an input sentence/paragraph.
            num_gpus (int, optional): The number of GPUs to use.
                If None, all available GPUs will be used. Defaults to None.
            num_epochs (int, optional): Number of training epochs.
                Defaults to 1.
            batch_size (int, optional): Training batch size. Defaults to 32.
            learning_rate (float, optional): learning rate of the BertAdam
                optimizer. Defaults to 2e-5.
            warmup_proportion (float, optional): Proportion of training to
                perform linear learning rate warmup for. E.g., 0.1 = 10% of
                training. Defaults to None.
        """

        train_dataloader = create_data_loader(
            input_ids=token_ids,
            input_mask=input_mask,
            label_ids=labels,
            sample_method="random",
            batch_size=batch_size,
        )

        device = get_device("cpu" if num_gpus == 0 else "gpu")
        self.model = move_to_device(self.model, device, num_gpus)

        if num_gpus is None:
            num_gpus_used = torch.cuda.device_count()
        else:
            num_gpus_used = min(num_gpus, torch.cuda.device_count())

        num_train_optimization_steps = (
            int(len(token_ids) / batch_size) * num_epochs
        )
        optimizer = self._get_optimizer(
            learning_rate=learning_rate,
            num_train_optimization_steps=num_train_optimization_steps,
            warmup_proportion=warmup_proportion,
        )

        self.model.train()
        for _ in trange(int(num_epochs), desc="Epoch"):
            tr_loss = 0
            nb_tr_steps = 0
            for step, batch in enumerate(
                tqdm(train_dataloader, desc="Iteration", mininterval=30)
            ):
                batch = tuple(t.to(device) for t in batch)
                b_token_ids, b_input_mask, b_label_ids = batch

                loss = self.model(
                    input_ids=b_token_ids,
                    attention_mask=b_input_mask,
                    labels=b_label_ids,
                )

                if num_gpus_used > 1:
                    # mean() to average on multi-gpu.
                    loss = loss.mean()
                # Accumulate parameter gradients
                loss.backward()

                tr_loss += loss.item()
                nb_tr_steps += 1

                # Update parameters based on current gradients
                optimizer.step()
                # Reset parameter gradients to zero
                optimizer.zero_grad()

            train_loss = tr_loss / nb_tr_steps
            print("Train loss: {}".format(train_loss))

    def predict(
        self, token_ids, input_mask, labels=None, batch_size=32, num_gpus=None
    ):
        """
        Predict token labels on the testing data.

        Args:
            token_ids (list): List of lists. Each sublist contains
                numerical token ids corresponding to the tokens in the input
                text data.
            input_mask (list): List of lists. Each sublist contains
                the attention mask of the input token list, 1 for input
                tokens and 0 for padded tokens, so that padded tokens are
                not attended to.
            labels (list, optional): List of lists. Each sublist contains
                numerical token labels of an input sentence/paragraph.
                If provided, it's used to compute the evaluation loss.
                Default value is None.
            batch_size (int, optional): Testing batch size. Defaults to 32.
            num_gpus (int, optional): The number of GPUs to use.
                If None, all available GPUs will be used. Defaults to None.

        Returns:
            list: List of lists of predicted token labels.
        """
        test_dataloader = create_data_loader(
            input_ids=token_ids,
            input_mask=input_mask,
            label_ids=labels,
            batch_size=batch_size,
            sample_method="sequential",
        )
        device = get_device("cpu" if num_gpus == 0 else "gpu")
        self.model = move_to_device(self.model, device, num_gpus)

        self.model.eval()
        predictions = []
        eval_loss = 0
        nb_eval_steps = 0
        for step, batch in enumerate(
            tqdm(test_dataloader, desc="Iteration", mininterval=10)
        ):
            batch = tuple(t.to(device) for t in batch)
            true_label_available = False
            if labels:
                b_input_ids, b_input_mask, b_labels = batch
                true_label_available = True
            else:
                b_input_ids, b_input_mask = batch

            with torch.no_grad():
                logits = self.model(b_input_ids, attention_mask=b_input_mask)
                if true_label_available:
                    active_loss = b_input_mask.view(-1) == 1
                    active_logits = logits.view(-1, self.num_labels)[
                        active_loss
                    ]
                    active_labels = b_labels.view(-1)[active_loss]
                    loss_fct = nn.CrossEntropyLoss()
                    tmp_eval_loss = loss_fct(active_logits, active_labels)

                    eval_loss += tmp_eval_loss.mean().item()

            logits = logits.detach().cpu().numpy()
            predictions.extend([list(p) for p in np.argmax(logits, axis=2)])

            nb_eval_steps += 1

        if true_label_available:
            validation_loss = eval_loss / nb_eval_steps
            print("Evaluation loss: {}".format(validation_loss))

        return predictions


def postprocess_token_labels(
    labels,
    input_mask,
    label_map=None,
    remove_trailing_word_pieces=False,
    trailing_token_mask=None,
):
    """
    Postprocesses token classification output:
        1) Removes predictions on padded tokens.
        2) If label_map is provided, maps predicted numerical labels
            back to original labels.
        3) If remove_trailing_word_pieces is True and trailing_token_mask
            is provided, remove the predicted labels on trailing word pieces
            generated by WordPiece tokenizer.

    Args:
        labels (list): List of lists of predicted token labels.
        input_mask (list): List of lists. Each sublist contains the attention
            mask of the input token list, 1 for input tokens and 0
            for padded tokens.
        label_map (dict, optional): A dictionary mapping original labels
            (which may be string type) to numerical label ids. If
            provided, it's used to map predicted numerical labels back to
            original labels. Default value is None.
        remove_trailing_word_pieces (bool, optional): Whether to remove
            predicted labels of trailing word pieces generated by WordPiece
            tokenizer. For example, "playing" is broken into "play" and
            "##ing". After removing predicted label for "##ing",
            the predicted label for "play" is assigned to the original word
            "playing". Default value is False.
        trailing_token_mask (list, optional): list of boolean values, True for
            the first word piece of each original word, False for trailing
            word pieces, e.g. ##ing. If remove_trailing_word_pieces is
            True, this mask is used to remove the predicted labels on
            trailing word pieces, so that each original word in the input
            text has a unique predicted label.
    """
    if label_map:
        reversed_label_map = {v: k for k, v in label_map.items()}
        labels_org = [[reversed_label_map[l_i] for l_i in l] for l in labels]
    else:
        labels_org = labels

    labels_org_no_padding = [
        [label for label, mask in zip(label_list, mask_list) if mask == 1]
        for label_list, mask_list in zip(labels_org, input_mask)
    ]

    if remove_trailing_word_pieces and trailing_token_mask:
        # Remove the padded values in trailing_token_mask first
        token_mask_no_padding = [
            [token for token, padding in zip(t_mask, p_mask) if padding == 1]
            for t_mask, p_mask in zip(trailing_token_mask, input_mask)
        ]

        labels_no_trailing_pieces = [
            [label for label, mask in zip(label_list, mask_list) if mask]
            for label_list, mask_list in zip(
                labels_org_no_padding, token_mask_no_padding
            )
        ]
        return labels_no_trailing_pieces
    else:
        return labels_org_no_padding
