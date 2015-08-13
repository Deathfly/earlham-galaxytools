#!/usr/bin/perl
#
use strict;
use warnings;


#A simple perl parser to convert hcluster_sg 3-column output into list of ids in separate files
#hcluster_sg_parser.pl <file>
#

my @table;
my @cluster_ids;
my $file1 = $ARGV[0];
open my $fh1, '<', $file1;
my $i = 0;

#reads through file
while (my $line = <$fh1>) {
    chomp $line;
    my @row = split(/\t/, $line);

    push @cluster_ids, $row[0];

    my @list = split(/\,/, $row[2]);
    $table[$i] = [@list];

    $i++;
}
close $fh1;

$i = 0;

#write into separate files with name of cluster_id
foreach my $row (@table) {
    my $outfile = $cluster_ids[$i]."_output.txt";
    open(my $fh, '>', $outfile) or die "Could not open file '$outfile' for writing: $!";

    foreach my $element (@$row) {
        print $fh $element, "\n";
    }

    close $fh;
    $i++;
}
