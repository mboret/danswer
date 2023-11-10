import argparse
import json
import os
import sys
from datetime import datetime
from os import listdir
from os.path import isfile
from os.path import join
from typing import Optional

import requests

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from danswer.configs.app_configs import APP_PORT, DOCUMENT_INDEX_NAME  # noqa: E402
from danswer.configs.constants import SOURCE_TYPE  # noqa: E402

REG_FOLDER = f"{parent_dir}/scripts/.regfiles/"


def color_output(
    text: str,
    model: Optional[str] = None,
    text_color: str = "black",
    bg_color: str = "transparent",
    text_style: str = "normal",
    text_prefix: str = "",
) -> None:
    """Color and print a text

    Args:
        text (str): The text to display
        model (str, optional): A pre-defined output model. Defaults to None.
        text_color (str, optional): Define the text color. Defaults to "black".
        bg_color (str, optional): Define the background color. Defaults to "transparent".
        text_style (str, optional): Define the text style. Defaults to "normal".
        text_prefix (str, optional): Set a text prefix. Defaults to "".
    """
    if model:
        if model == "alert":
            text_color = "black"
            bg_color = "red"
            text_style = "bold"
        elif model == "critical":
            text_prefix = "CRITICAL: "
            text_color = "black"
            bg_color = "red"
            text_style = "bold"
        elif model == "note":
            text_color = "yellow"
            bg_color = "transparent"
            text_style = "normal"
        elif model == "info":
            text_prefix = "INFO:     "
            text_color = "black"
            bg_color = "yellow"
            text_style = "bold"
        elif model == "info2":
            text_prefix = "INFO:     "
            text_color = "black"
            bg_color = "white"
            text_style = "bold"
        elif model == "valid":
            text_prefix = "INFO:     "
            text_color = "white"
            bg_color = "green"
            text_style = "bold"
        elif model == "debug":
            text_prefix = "DEBUG:    "
            text_color = "blue"
            bg_color = "transparent"
            text_style = "bold"

    text_colors = {
        "black": 30,
        "red": 31,
        "green": 32,
        "yellow": 33,
        "blue": 34,
        "purple": 35,
        "cian": 36,
        "white": 37,
    }
    bg_colors = {
        "black": 40,
        "red": 41,
        "green": 42,
        "yellow": 43,
        "blue": 44,
        "purple": 45,
        "cian": 46,
        "white": 47,
        "transparent": 49,
    }
    text_styles = {
        "normal": 0,
        "bold": 1,
        "light": 2,
        "italicized": 3,
        "underlined": 4,
        "blink": 5,
    }
    print(
        f"\033[{text_styles[text_style]};{text_colors[text_color]};{bg_colors[bg_color]}m {text_prefix} {text} \033[0;0m"
    )


class CompareAnalysis:
    def __init__(
        self, query: str, previous_content: dict, new_content: dict, threshold: float
    ) -> None:
        """Make the comparison between 2 analysis for a specific query

        Args:
            query (str): The analysed query
            previous_content (dict): The previous analysis content for the selected query
            new_content (dict): The new analysis content for the selected query
            threshold (float): The minimum difference (percentage) between scores to raise an anomaly
        """
        self._query = query
        self._previous_content = previous_content
        self._new_content = new_content
        self._threshold = threshold

    def _identify_diff(self, content_key: str) -> list[dict]:
        """Try to identify differences between the two analysis based
            on the selected analysis key.

        Args:
            content_key (str): The analysis item's key to compare the versions.
                                Examples: score / document_id

        Returns:
            list[dict]: List of dict representing the information regarding the difference
                        Format: {
                                    "previous_rank": XX,
                                    "new_rank": XX,
                                    "document_id": XXXX,
                                    "previous_score": XX,
                                    "new_score": XX,
                                    "score_change_pct": XX
                                }
        """
        changes = []

        previous_content = {
            k: v[content_key] for k, v in self._previous_content.items()
        }
        new_content = {k: v[content_key] for k, v in self._new_content.items()}

        if previous_content != new_content:
            for pos, data in previous_content.items():
                if data != new_content[pos]:
                    try:
                        score_change_pct = round(
                            (
                                abs(
                                    self._new_content[pos]["score"]
                                    - self._previous_content[pos]["score"]
                                )
                                / self._new_content[pos]["score"]
                            )
                            * 100.0,
                            2,
                        )
                    except ZeroDivisionError:
                        score_change_pct = 0

                    changes.append(
                        {
                            "previous_rank": pos,
                            "new_rank": pos
                            if content_key == "score"
                            else {
                                "x": k for k, v in new_content.items() if v == data
                            }.get("x", "not_ranked"),
                            "document_id": self._previous_content[pos]["document_id"],
                            "previous_score": self._previous_content[pos]["score"],
                            "new_score": self._new_content[pos]["score"],
                            "score_change_pct": score_change_pct,
                        }
                    )
        return changes

    def check_config_changes(self, previous_doc_rank: int, new_doc_rank: int) -> None:
        """Try to identify possible reasons why a change has been detected by
            checking the latest document update date or the boost value.

        Args:
            previous_doc_rank (int): The document rank for the previous analysis
            new_doc_rank (int): The document rank for the new analysis
        """
        if new_doc_rank == "not_ranked":
            color_output(
                (
                    "NOTE: The document is missing in the 'current' regression file. "
                    "Unable to identify more details about the reason for the change."
                ),
                model="note",
            )
            return None

        if (
            self._previous_content[previous_doc_rank]["boost"]
            != self._new_content[new_doc_rank]["boost"]
        ):
            color_output(
                "NOTE: The 'boost' value has been changed which (maybe) explains the change.",
                model="note",
            )
            color_output(
                (
                    f"Previously it was '{self._previous_content[previous_doc_rank]['boost']}' "
                    f"and now is set to '{self._new_content[new_doc_rank]['boost']}'"
                ),
                model="note",
            )
        if (
            self._previous_content[previous_doc_rank]["updated_at"]
            != self._new_content[new_doc_rank]["updated_at"]
        ):
            color_output("NOTE: The document seems to have been updated.", model="note")
            color_output(
                (
                    f"Previously the updated date was '{self._previous_content[previous_doc_rank]['updated_at']}' "
                    f"and now is '{self._new_content[new_doc_rank]['updated_at']}'"
                ),
                model="note",
            )

    def check_documents_score(self) -> bool:
        """Check if the scores have changed between analysis.

        Returns:
            bool: True if at least one change has been detected. False otherwise.
        """
        color_output("Checking documents Score....", model="info")
        color_output(
            f"Differences under '{self._threshold}%' are ignored (based on the '--threshold' argument)",
            model="info",
        )

        if diff := [
            x
            for x in self._identify_diff("score")
            if x["score_change_pct"] > self._threshold
        ]:
            color_output("<<<<< Changes detected >>>>>", model="alert")
            for change in diff:
                color_output("-" * 100)
                color_output(
                    (
                        f"The document '{change['document_id']}' (rank: {change['previous_rank']}) "
                        f"score has a changed of {change['score_change_pct']}%"
                    )
                )
                color_output(f"previous score: {change['previous_score']}")
                color_output(f"current score:  {change['new_score']}")
                self.check_config_changes(change["previous_rank"], change["new_rank"])

            color_output("<<<<< End of changes >>>>>", model="alert")
            color_output(f"Number of changes detected {len(diff)}", model="info")
        else:
            color_output("No change detected", model="valid")
        color_output("Documents Score check completed.", model="info")

        return False if diff else True

    def check_documents_order(self) -> bool:
        """Check if the selected documents are the same and in the same order.

        Returns:
            bool: True if at least one change has been detected. False otherwise.
        """
        color_output("Checking documents Order....", model="info")

        if diff := self._identify_diff("document_id"):
            color_output("<<<<< Changes detected >>>>>", model="alert")
            for change in diff:
                color_output("-" * 100)
                color_output(
                    (
                        f"The document '{change['document_id']}' was at a rank "
                        f"'{change['previous_rank']}' but now is at rank '{change['new_rank']}'"
                    )
                )
                color_output(f"previous score: {change['previous_score']}")
                color_output(f"current score:  {change['new_score']}")
                self.check_config_changes(change["previous_rank"], change["new_rank"])
            color_output("<<<<< End of changes >>>>>", model="alert")
            color_output(f"Number of changes detected {len(diff)}", model="info")

        else:
            color_output("No change detected", model="valid")
        color_output("Documents order check completed.", model="info")

        return False if diff else True

    def __call__(self) -> None:
        """Manage the analysis process"""
        if not self.check_documents_order():
            color_output(
                "Skipping other checks as the documents order has changed", model="info"
            )
            return None

        self.check_documents_score()


class RegAnalysis:
    def __init__(
        self,
        exectype: str,
        regfiles: list = [],
        queries: list = [],
        threshold: float = 0.0,
    ) -> None:
        """

        Args:
            exectype (str): The execution mode (new or compare)
            regfiles (list, optional): List of regression files to compare or if only one, to use as the base. Defaults to [].
                                        Requiered only by the 'compare' mode
            queries (list, optional): The queries to analysed. Defaults to [].
                                        Required only by the 'new' mode
            threshold (float): The minimum difference (percentage) between scores to raise an anomaly
        """
        self._exectype = exectype
        self._regfiles = regfiles
        self._queries = queries
        self._threshold = threshold

    def do_request(self, query: str) -> dict:
        """Request the Danswer API

        Args:
            query (str): A query

        Returns:
            dict: The Danswer API response content
        """
        endpoint = f"http://127.0.0.1:{APP_PORT}/direct-qa"
        query_json = {
            "query": query,
            "collection": DOCUMENT_INDEX_NAME,
            "filters": {SOURCE_TYPE: None},
            "enable_auto_detect_filters": True,
            "search_type": "hybrid",
            "offset": 0,
            "favor_recent": True,
        }
        try:
            response = requests.post(endpoint, json=query_json)
            if response.status_code != 200:
                color_output(
                    (
                        "something goes wrong while requesting the Danswer API "
                        f"for the query '{query}': {response.text}"
                    ),
                    model="critical",
                )
                sys.exit(1)
        except Exception as e:
            color_output(
                f"Unable to request the Danswer API for the query '{query}': {e}",
                model="critical",
            )
            sys.exit(1)

        return json.loads(response.content)

    def get_regression_files(self) -> list[str]:
        """Returns the list of existing regression files.

        Returns:
            list[str]: List of filename
        """
        return [f for f in listdir(REG_FOLDER) if isfile(join(REG_FOLDER, f))]

    def get_regression_file_content(self, filename: str) -> list[dict]:
        """Returns the content of a regression file

        Args:
            filename (str): The regression filename

        Returns:
            list[dict]: Content of the selected file
        """
        with open(f"{REG_FOLDER}{filename}", "r") as f:
            return json.load(f)

    def extract_content(self, contents: dict) -> dict:
        """Extract the content returns by the Danswer API

        Args:
            contents (dict): The danswer response content

        Returns:
            dict: Data regarding the selected sources document
        """
        return {
            pos: doc
            for pos, doc in enumerate(
                sorted(
                    contents["top_ranked_docs"], key=lambda d: d["score"], reverse=True
                )[:5]
            )
        }

    def save_regfile(self, content: list[dict]) -> Optional[str]:
        """Save the extracted content

        Args:
            content (list[dict]): The content to save

        Returns:
            str: The filname
        """
        filename = datetime.now().strftime("%Y_%m_%d-%I_%M_%S")
        reg_file = f"{REG_FOLDER}{filename}.json"

        try:
            with open(reg_file, "w") as f:
                json.dump(content, f, indent=4)
        except Exception as e:
            color_output(f"Unable to create the regression file: {e}", model="critical")
            return None

        color_output(f"Regression file created: {reg_file}", model="debug")
        return reg_file

    def new(self) -> Optional[str]:
        """Manage the process to create a new analysis file
            based on the submitted queries

        Returns:
            str: The new filename with the analysis content
        """
        if not self._queries:
            color_output("Missing queries", model="critical")
            sys.exit(1)

        color_output("Generating a new regression file...", model="debug")
        regfile = []

        for query in self._queries:
            color_output(f"Let's evaluate the query: '{query}'", model="debug")
            contents = self.do_request(query)

            regfile.append(
                {"query": query, "selected_documents": self.extract_content(contents)}
            )

        return self.save_regfile(regfile)

    def compare(
        self, previous_regfile_content: list[dict], new_regfile_content: list[dict]
    ) -> None:
        """Manage the process to compare two analysis

        Args:
            previous_regfile_content (list): Previous content analysis
            new_regfile_content (list): New content analysis
        """
        for query in self._queries:
            # Extract data regarding the selected source documents
            prev_querie_content = [
                x for x in previous_regfile_content if x["query"] == query
            ][0]["selected_documents"]
            new_querie_content = [
                x for x in new_regfile_content if x["query"] == query
            ][0]["selected_documents"]

            color_output(f"Analysing the query: '{query}'", model="info2")
            CompareAnalysis(
                query, prev_querie_content, new_querie_content, self._threshold
            )()
            color_output(f"Analyse completed for the query: '{query}'", model="info2")

        color_output("All the defined queries have been evaluated.", model="info2")

    def validate_regfiles(self) -> bool:
        """Validate that the selected regressions files exist

        Returns:
            bool: True if all of them exist. False otherwise
        """
        existing_regfiles = self.get_regression_files()

        if missing_regfiles := [
            x for x in self._regfiles if x not in existing_regfiles
        ]:
            color_output(
                f"Missing regression file(s) '{', '.join(missing_regfiles)}' - NOT FOUND",
                model="critical",
            )
            regfiles = "\n ".join(existing_regfiles)
            color_output("Available regression files:", model="info2")
            color_output(regfiles)
            return False

        return True

    def __call__(self) -> None:
        if self._exectype == "new":
            self.new()
        elif self._exectype == "compare":
            self._regfiles = [x.replace(".json", "") + ".json" for x in self._regfiles]

            if not self.validate_regfiles():
                sys.exit(1)

            color_output(
                "Extracting queries from the existing reg file...", model="debug"
            )
            previous_regfile_content = self.get_regression_file_content(
                self._regfiles[0]
            )

            # Extract the queries
            self._queries = sorted([x["query"] for x in previous_regfile_content])
            color_output(
                f"Extracted queries: {', '.join(self._queries)}", model="debug"
            )

            if len(self._regfiles) == 1:
                if new_file := self.new():
                    new_regfile_content = self.get_regression_file_content(
                        new_file.split("/")[-1:][0]
                    )
                    return self.compare(previous_regfile_content, new_regfile_content)
                else:
                    color_output(
                        "Unable to generate a new regression file", model="critical"
                    )
                    sys.exit(1)
            else:
                color_output(
                    (
                        f"For the rest of this execution, the reg file '{self._regfiles[0]}' "
                        "is identified as 'previous' and '{self._regfiles[1]}' as 'current'"
                    ),
                    model="info2",
                )
                new_regfile_content = self.get_regression_file_content(
                    self._regfiles[1]
                )
                new_queries = sorted([x["query"] for x in new_regfile_content])
                if new_queries != self._queries:
                    color_output(
                        "Unable to compare regression files as the queries are differents",
                        model="critical",
                    )
                    sys.exit(1)
                self.compare(previous_regfile_content, new_regfile_content)


def validate_cmd_args(args: argparse.Namespace) -> bool:
    """Validate the CMD arguments

    Args:
        args (argparse.Namespace): The argparse data input

    Returns:
        bool: True if the CMD arguments are valid. False otherwise
    """
    if args.execution == "new" and not args.q__queries:
        color_output(
            "Missing argument. When the execution type is set to 'new' the '--queries' argument must be defined",
            model="critical",
        )
        return False
    elif args.execution == "compare":
        if not args.regfiles:
            color_output(
                "Missing argument. When the execution type is set to 'compare' the '--regfiles' argument must be defined",
                model="critical",
            )
            return False
        elif len(args.regfiles) > 2:
            color_output(
                "Too many arguments. The '--regfiles' argument cannot be repeated more than 2 times.",
                model="critical",
            )
            return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-e",
        "--execution",
        type=str,
        choices=["new", "compare"],
        default="new",
        help=(
            "The execution type. Must be 'new' to generate a new regression file "
            "or 'compare' to compare a previous execution with a new one based on the same queries"
        ),
    )

    parser.add_argument(
        "-r",
        "--regfiles",
        action="extend",
        default=[],
        nargs=1,
        help=(
            "Regression file(s) to use for the comparison. Required if the execution arg is set "
            "to 'compare'. NOTE: By repeating this argument, you can make a comparison between "
            "two specific executions. If not repeated, a new execution will be performed"
        ),
    )

    parser.add_argument(
        "-q" "--queries",
        type=str,
        action="extend",
        default=[],
        nargs=1,
        help=(
            "The query to evaluate. Required if the execution arg is set to 'new'. "
            "NOTE: This argument can be repeated multiple times"
        ),
    )

    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.0,
        help="The minimum score change (percentage) to detect an issue.",
    )

    args = parser.parse_args()
    if not validate_cmd_args(args):
        sys.exit(1)

    RegAnalysis(args.execution, args.regfiles, args.q__queries, args.threshold)()
