#!/usr/bin/env python3
# Author: Heskemo, HKM Technologies Inc.
#
from __future__ import print_function

import argparse as ap
import ast
import re
import subprocess
import sys


def get_version():
    responses = subprocess.check_output(['solc', '--version']).decode().split()
    for r in responses:
        try:
            return re.findall('([0-9]+\.[0-9]+\.[0-9]+)\+commit', r)[0]
        except IndexError:
            continue
    return "0.4.13"


def flatten_contract(solc_AST, output_dest):
    contract_regex = re.compile(r'(ContractDefinition \"(.+)\"(?:\n\s+Gas costs: \d+)?\n(?: +.+\n)+)')
    contract_source_regex = re.compile(r'ContractDefinition \".+\"(?:\n\s+Gas costs: \d+)?\n +Source: "(.+)"')
    inheritance_regex = re.compile(r'InheritanceSpecifier(?:\n\s+Gas costs: \d+)?\n\s+Source: "(.+)"')
    using_for_regex = re.compile(r'\n  UserDefinedTypeName "(.+)"')

    contracts = contract_regex.findall(solc_AST)
    contract_sources = {}
    dependency_graph = {}
    full_dependency_set = set()
    for c in contracts:
        contract_name = c[1]
        contract_ast = c[0]
        # print("="*8 + contract_name + "="*8)
        # print(contract_ast)

        if contract_name in dependency_graph:
            print("FATAL: '{name}' was defined multiple times. Aborting.".format(name=contract_name), file=sys.stderr)
            return

        # Pull inheritances
        inheritances = set(inheritance_regex.findall(contract_ast))
        fixedInheritances = set([inheritance.split("(")[0] for inheritance in inheritances])
        using_fors = set(using_for_regex.findall(contract_ast))
        dep_set = fixedInheritances | using_fors
        dependency_graph[contract_name] = dep_set
        full_dependency_set.update(dep_set)

        # Pull contract source
        found_contract_source = contract_source_regex.search(contract_ast)
        if not found_contract_source:
            print("FATAL: '{name}' has no attached contract source. Aborting.".format(name=contract_name),
                  file=sys.stderr)
            return

        contract_sources[contract_name] = found_contract_source.group(1)

    contracts_with_sources = set(contract_sources.keys())
    # print(dependency_graph)
    # print(contracts_with_sources)
    # print(full_dependency_set)

    if not full_dependency_set.issubset(contracts_with_sources):
        # We require a dependency that we do not have a contract source for, cannot continue
        print("FATAL: Missing sources for the following contracts: {}".format(
            full_dependency_set - contracts_with_sources), file=sys.stderr)
        return

    processed_contracts = set()
    output_solidity_code = "pragma solidity %s;\n\n" % get_version()
    while processed_contracts != contracts_with_sources:
        # print(processed_contracts, "vs", contracts_with_sources)
        for cname, cdepends in dependency_graph.items():
            if cdepends.issubset(processed_contracts):
                # Found a contract that has its dependencies satisfied
                to_concat = cname
                break

        if to_concat is None:
            print("FATAL: Exhausted contract list and could not find a satisfiable dependency.", file=sys.stderr)
            print("\tUnsatisfied contracts:", file=sys.stderr)
            for unsat_depend in (contracts_with_sources - processed_contracts):
                print("\t\t" + unsat_depend + " (requires: {})".format(dependency_graph[unsat_depend]), file=sys.stderr)
            return

        output_solidity_code += ast.literal_eval('\"' + contract_sources[cname] + '\"') + "\n\n"
        processed_contracts.update([cname])
        del dependency_graph[cname]

    output_dest.write(output_solidity_code)


def execute():
    parser = ap.ArgumentParser(
        description="Flattens a target Solidity source file by resolving all of its imports and dependencies.\n \
					 NOTE: This does not work with imports that are aliased (i.e. import './A.sol' as B; )")
    parser.add_argument(
        "target_solidity_file",
        help="Specifies the target Solidity source file to flatten.")
    parser.add_argument(
        "--output", type=ap.FileType('w+'), default=sys.stdout, metavar="FILENAME",
        help="Specifies the output destination filename. Outputs to stdout by default.")
    parser.add_argument(
        "--solc-paths", default="",
        help="Specifies the path replacements to pass onto solidity. See solc --help for more information.")
    parser.add_argument(
        "--allow-paths", default="",
        help="Specify list of paths (comma separated) to allow solc to import files from. See solc --help for more information.")
    args = parser.parse_args()

    solc_args = ["solc"]
    solc_args += [args.solc_paths] if args.solc_paths else []
    solc_args += ["--ast"]
    solc_args += ["--allow-paths", args.allow_paths] if args.allow_paths else []
    solc_args += ["--optimize-yul"]
    solc_args += [args.target_solidity_file]

    solc_proc = subprocess.run(solc_args, stdout=subprocess.PIPE, universal_newlines=True)
    solc_proc.check_returncode()
