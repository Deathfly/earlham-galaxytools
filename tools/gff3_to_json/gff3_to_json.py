from __future__ import print_function

import json
import optparse
import sys

cds_parent_dict = dict()
exon_parent_dict = dict()
five_prime_utr_parent_dict = dict()
gene_count = 0
gene_dict = dict()
transcript_dict = dict()
three_prime_utr_parent_dict = dict()


def feature_to_json(cols):
    d = {
        'end': int(cols[4]),
        'start': int(cols[3]),
    }
    for attr in cols[8].split(';'):
        if '=' in attr:
            (tag, value) = attr.split('=')
            if tag == 'ID':
                d['id'] = value
            else:
                d[tag] = value
    if cols[6] == '+':
        d['strand'] = 1
    elif cols[6] == '-':
        d['strand'] = -1
    else:
        raise Exception("Unrecognized strand '%s'" % cols[6])
    return d


def gene_to_json(cols, species):
    global gene_count
    gene = feature_to_json(cols)
    gene.update({
        'member_id': gene_count,
        'object_type': 'Gene',
        'seq_region_name': cols[0],
        'species': species,
        'Transcript': [],
    })
    gene_dict[gene['id']] = gene
    gene_count = gene_count + 1


def transcript_to_json(cols, species):
    transcript = feature_to_json(cols)
    transcript.update({
        'object_type': 'Transcript',
        'seq_region_name': cols[0],
        'species': species,
    })
    transcript_dict[transcript['id']] = transcript


def exon_to_json(cols, species):
    exon = feature_to_json(cols)
    exon.update({
        'length': int(cols[4]) - int(cols[3]) + 1,
        'object_type': 'Exon',
        'seq_region_name': cols[0],
        'species': species,
    })
    if 'id' not in exon and 'Name' in exon:
        exon['id'] = exon['Name']

    if 'Parent' in exon:
        for parent in exon['Parent'].split(','):
            if parent not in exon_parent_dict:
                exon_parent_dict[parent] = [exon]
            else:
                exon_parent_dict[parent].append(exon)


def five_prime_utr_to_json(cols):
    five_prime_utr = feature_to_json(cols)
    if 'Parent' in five_prime_utr:
        for parent in five_prime_utr['Parent'].split(','):
            # the 5' UTR can be split among multiple exons
            if parent not in five_prime_utr_parent_dict:
                five_prime_utr_parent_dict[parent] = [five_prime_utr]
            else:
                five_prime_utr_parent_dict[parent].append(five_prime_utr)


def three_prime_utr_to_json(cols):
    three_prime_utr = feature_to_json(cols)
    if 'Parent' in three_prime_utr:
        for parent in three_prime_utr['Parent'].split(','):
            # the 3' UTR can be split among multiple exons
            if parent not in three_prime_utr_parent_dict:
                three_prime_utr_parent_dict[parent] = [three_prime_utr]
            else:
                three_prime_utr_parent_dict[parent].append(three_prime_utr)


def cds_to_json(cols):
    cds = feature_to_json(cols)
    if 'id' not in cds:
        if 'Name' in cds:
            cds['id'] = cds['Name']
        elif 'Parent' in cds:
            cds['id'] = cds['Parent']
    if 'Parent' in cds:
        # At this point we are sure than 'id' is in cds
        for parent in cds['Parent'].split(','):
            if parent not in cds_parent_dict:
                cds_parent_dict[parent] = [cds]
            else:
                cds_parent_dict[parent].append(cds)


def join_dicts():
    for parent, exon_list in exon_parent_dict.items():
        exon_list.sort(key=lambda _: _['start'])
        if parent in transcript_dict:
            transcript_dict[parent]['Exon'] = exon_list

    for transcript_id, transcript in transcript_dict.items():
        translation = {
            'CDS': [],
            'id': None,
            'end': transcript['end'],
            'object_type': 'Translation',
            'species': transcript['species'],
            'start': transcript['start'],
        }
        found_cds = False
        derived_translation_start = None
        derived_translation_end = None
        if transcript_id in cds_parent_dict:
            cds_list = cds_parent_dict[transcript_id]
            cds_ids = set(_['id'] for _ in cds_list)
            if len(cds_ids) > 1:
                raise Exception("Transcript %s has multiple CDSs: this is not supported by Ensembl JSON format" % parent)
            translation['id'] = cds_ids.pop()
            cds_list.sort(key=lambda _: _['start'])
            translation['CDS'] = cds_list
            translation['start'] = cds_list[0]['start']
            translation['end'] = cds_list[-1]['end']
            found_cds = True
        if transcript_id in five_prime_utr_parent_dict:
            five_prime_utr_list = five_prime_utr_parent_dict[transcript_id]
            five_prime_utr_list.sort(key=lambda _: _['start'])
            if transcript['strand'] == 1:
                derived_translation_start = five_prime_utr_list[-1]['end'] + 1
            else:
                derived_translation_end = five_prime_utr_list[0]['start'] - 1
        if transcript_id in three_prime_utr_parent_dict:
            three_prime_utr_list = three_prime_utr_parent_dict[transcript_id]
            three_prime_utr_list.sort(key=lambda _: _['start'])
            if transcript['strand'] == 1:
                derived_translation_end = three_prime_utr_list[0]['start'] - 1
            else:
                derived_translation_start = three_prime_utr_list[-1]['end'] + 1
        if derived_translation_start is not None:
            if found_cds:
                if derived_translation_start > translation['start']:
                    raise Exception("UTR overlaps with CDS")
            else:
                translation['start'] = derived_translation_start
        if derived_translation_end is not None:
            if found_cds:
                if derived_translation_end < translation['end']:
                    raise Exception("UTR overlaps with CDS")
            else:
                translation['end'] = derived_translation_end
        if found_cds or derived_translation_start is not None or derived_translation_end is not None:
            transcript['Translation'] = translation

    for transcript in transcript_dict.values():
        if 'Parent' in transcript:
            # A polycistronic transcript can have multiple parents
            for parent in transcript['Parent'].split(','):
                if parent in gene_dict:
                    gene_dict[parent]['Transcript'].append(transcript)


def merge_dicts(json_arg):
    with open(json_arg) as f:
        dict_from_json = json.load(f)
    gene_intersection = set(gene_dict.keys()) & set(dict_from_json.keys())
    if gene_intersection:
        raise Exception("JSON file '%s' contains information for genes '%s', which are also present in other files" % (json_arg, ', '.join(gene_intersection)))
    gene_dict.update(dict_from_json)


def write_json(outfile=None, sort_keys=False):
    if outfile:
        with open(outfile, 'w') as f:
            json.dump(gene_dict, f, sort_keys=sort_keys)
    else:
        print(json.dumps(gene_dict, indent=3, sort_keys=sort_keys))


def __main__():
    parser = optparse.OptionParser()
    parser.add_option('--gff3', action='append', default=[], help='GFF3 file to convert, in SPECIES:FILENAME format. Use multiple times to add more files')
    parser.add_option('--json', action='append', default=[], help='JSON file to merge. Use multiple times to add more files')
    parser.add_option('-s', '--sort', action='store_true', help='Sort the keys in the JSON output')
    parser.add_option('-o', '--output', help='Path of the output file. If not specified, will print on the standard output')
    options, args = parser.parse_args()

    if args:
        raise Exception('Use options to provide inputs')
    for gff3_arg in options.gff3:
        try:
            (species, filename) = gff3_arg.split(':')
        except ValueError:
            raise Exception("Argument for --gff3 '%s' is not in the SPECIES:FILENAME format" % gff3_arg)
        with open(filename) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    # skip empty lines
                    continue
                if line[0] == '#':
                    # skip comment lines
                    continue
                cols = line.split('\t')
                if len(cols) != 9:
                    raise Exception("Line %i in file '%s': '%s' does not have 9 columns" % (i, filename, line))
                feature_type = cols[2]
                try:
                    if feature_type == 'gene':
                        gene_to_json(cols, species)
                    elif feature_type in ('mRNA', 'transcript'):
                        transcript_to_json(cols, species)
                    elif feature_type == 'exon':
                        exon_to_json(cols, species)
                    elif feature_type == 'five_prime_UTR':
                        five_prime_utr_to_json(cols)
                    elif feature_type == 'three_prime_UTR':
                        three_prime_utr_to_json(cols)
                    elif feature_type == 'CDS':
                        cds_to_json(cols)
                    else:
                        print("Line %i in file '%s': '%s' is not an implemented feature type" % (i, filename, feature_type), file=sys.stderr)
                except Exception as e:
                    raise Exception("Line %i in file '%s': %s" % (i, filename, e))
    join_dicts()

    for json_arg in options.json:
        merge_dicts(json_arg)

    write_json(options.output, options.sort)


if __name__ == '__main__':
    __main__()
