import os
import sys

import pandas as pd


class SentEvalRunner(object):
    def __init__(self, path_to_senteval="."):
        """AzureML-compatible wrapper class that interfaces with the
           original implementation of SentEval

        Args:
            path_to_senteval (str, optional): Path to the SentEval source code.
            use_azureml (bool, optional): Defaults to False.
        """
        self.path_to_senteval = path_to_senteval

    def set_transfer_data_path(self, relative_path):
        """Set the datapath that contains the datasets for the SentEval transfer tasks

        Args:
            relative_path (str): Relative datapath
        """
        self.transfer_data_path = os.path.join(self.path_to_senteval, relative_path)

    def set_transfer_tasks(self, task_list):
        """Set the transfer tasks to use for evaluation

        Args:
            task_list (list(str)): List of downstream transfer tasks
        """
        self.transfer_tasks = task_list

    def set_model(self, model):
        """Set the model to evaluate"""
        self.model = model

    def set_params_senteval(
        self,
        use_pytorch=True,
        kfold=10,
        nhid=0,
        optim="adam",
        batch_size=64,
        tenacity=5,
        epoch_size=4,
    ):
        """
        Define the required parameters for SentEval (model, task_path, usepytorch, kfold).
        Also gives the option to directly set parameters for a classifier if necessary.
        """
        self.params_senteval = {
            "model": self.model,
            "task_path": self.transfer_data_path,
            "usepytorch": use_pytorch,
            "kfold": kfold,
        }
        classifying_tasks = {
            "MR",
            "CR",
            "SUBJ",
            "MPQA",
            "SST2",
            "SST5",
            "TREC",
            "SICKEntailment",
            "SNLI",
            "MRPC",
        }
        if any(t in classifying_tasks for t in self.transfer_tasks):
            self.params_senteval["classifier"] = {
                "nhid": nhid,
                "optim": optim,
                "batch_size": batch_size,
                "tenacity": tenacity,
                "epoch_size": epoch_size,
            }

    def run(self, batcher_func, prepare_func):
        """Run the SentEval engine on the model on the transfer tasks

        Args:
            batcher_func (function): Function required by SentEval that transforms a batch of text sentences into
                                     sentence embeddings
            prepare_func (function): Function that sees the whole dataset of each task and can thus construct the word
                                     vocabulary, the dictionary of word vectors, etc

        Returns:
            dict: Dictionary of results
        """
        sys.path.insert(0, os.path.relpath(self.path_to_senteval, os.getcwd())
        import senteval

        se = senteval.engine.SE(
            self.params_senteval, batcher_func, prepare_func
        )

        return se.eval(self.transfer_tasks)

    #  TODO: This function does not print
    def print_mean(self, results, selected_metrics=[], round_decimals=3):
        """Print the means of selected metrics of the transfer tasks as a table

        Args:
            results (dict): Results from the SentEval evaluation engine
            selected_metrics (list(str), optional): List of metric names
            round_decimals (int, optional): Number of decimal digits to round to; defaults to 3
        """
        data = []
        for task in self.transfer_tasks:
            if "all" in results[task]:
                row = [
                    results[task]["all"][metric]["mean"]
                    for metric in selected_metrics
                ]
            else:
                row = [results[task][metric] for metric in selected_metrics]
            data.append(row)

        table = pd.DataFrame(
            data=data, columns=selected_metrics, index=self.transfer_tasks
        )
        return table.round(round_decimals)
