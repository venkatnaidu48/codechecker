# -------------------------------------------------------------------------
#
#  Part of the CodeChecker project, under the Apache License v2.0 with
#  LLVM Exceptions. See LICENSE for license information.
#  SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# -------------------------------------------------------------------------

import logging
import os
import xml.etree.ElementTree as ET

from typing import Dict, List, Optional

from codechecker_report_converter.report import BugPathEvent, \
    File, get_or_create_file, Report

from ..analyzer_result import AnalyzerResultBase


LOG = logging.getLogger('report-converter')


class AnalyzerResult(AnalyzerResultBase):
    """ Transform analyzer result of SpotBugs. """

    TOOL_NAME = 'spotbugs'
    NAME = 'spotbugs'
    URL = 'https://spotbugs.github.io'

    def __init__(self):
        super(AnalyzerResult, self).__init__()
        self.__project_paths = []
        self.__file_cache: Dict[str, File] = {}

    def get_reports(self, file_path: str) -> List[Report]:
        """ Parse the given analyzer result. """
        reports: List[Report] = []

        root = self.__parse_analyzer_result(file_path)
        if root is None:
            return reports

        self.__project_paths = self.__get_project_paths(root)

        for bug in root.findall('BugInstance'):
            report = self.__parse_bug(bug)
            if report:
                reports.append(report)

        return reports

    def __get_abs_path(self, source_path: str):
        """ Returns full path of the given source path.

        It will try to find the given source path in the project paths and
        returns full path if it founds.
        """
        if os.path.exists(source_path):
            return source_path

        for project_path in self.__project_paths:
            full_path = os.path.join(project_path, source_path)
            if os.path.exists(full_path):
                return full_path

        LOG.warning("No source file found: %s", source_path)

    def __parse_analyzer_result(self, analyzer_result: str):
        """ Parse the given analyzer result xml file.

        Returns the root element of the parsed tree or None if something goes
        wrong.
        """
        try:
            tree = ET.parse(analyzer_result)
            return tree.getroot()
        except OSError:
            LOG.error("Analyzer result does not exist: %s", analyzer_result)
        except ET.ParseError:
            LOG.error("Failed to parse the given analyzer result '%s'. Please "
                      "give a valid xml file with messages generated by "
                      "SpotBugs.", analyzer_result)

    def __get_project_paths(self, root):
        """ Get project paths from the bug collection. """
        paths = []

        project = root.find('Project')
        for element in project:
            if element.tag in ['Jar', 'AuxClasspathEntry', 'SrcDir']:
                file_path = element.text
                if os.path.isdir(file_path):
                    paths.append(file_path)
                elif os.path.isfile(file_path):
                    paths.append(os.path.dirname(file_path))

        return paths

    def __parse_bug(self, bug):
        """ Parse the given bug and create a message from them. """
        report_hash = bug.attrib.get('instanceHash')
        checker_name = bug.attrib.get('type')

        long_message = bug.find('LongMessage').text

        source_line = bug.find('SourceLine')
        source_path = self.__get_source_path(source_line)
        if not source_path:
            return

        line = source_line.attrib.get('start')
        col = 0

        events = []
        for element in list(bug):
            event = None
            if element.tag == 'Class':
                event = self.__event_from_class(element)
            elif element.tag == 'Method':
                event = self.__event_from_method(element)

            if event:
                events.append(event)

        # If <SourceLine> did not contain a 'start' attribute, take the last
        # of the events.
        if line is None:
            line = next((e.line for e in reversed(events) if e.line > 0), 0)

        report = Report(
            get_or_create_file(source_path, self.__file_cache),
            int(line),
            col,
            long_message,
            checker_name,
            report_hash=report_hash,
            bug_path_events=events)

        report.bug_path_events.append(BugPathEvent(
            report.message, report.file, report.line, report.column))

        return report

    def __event_from_class(self, element) -> Optional[BugPathEvent]:
        """ Creates event from a Class element. """
        message = element.find('Message').text

        source_line = element.find('SourceLine')
        source_path = self.__get_source_path(source_line)
        if not source_path:
            return None

        line = int(source_line.attrib.get('start', 0))
        col = 0

        return BugPathEvent(
            message,
            get_or_create_file(source_path, self.__file_cache),
            line,
            col)

    def __event_from_method(self, element) -> Optional[BugPathEvent]:
        """ Creates event from a Method element. """
        message = element.find('Message').text

        source_line = element.find('SourceLine')
        source_path = self.__get_source_path(source_line)
        if not source_path:
            return None

        line = int(source_line.attrib.get('start', 0))
        col = 0

        return BugPathEvent(
            message,
            get_or_create_file(source_path, self.__file_cache),
            line,
            col)

    def __get_source_path(self, source_line):
        """ Get source path from the source line. """
        if source_line is None:
            return None

        source_path_attrib = source_line.attrib.get('sourcepath')
        if source_path_attrib is None:
            LOG.warning("No source path attribute found for class: %s", source_line.attrib.get('classname'))
            return None

        return self.__get_abs_path(source_path_attrib)
