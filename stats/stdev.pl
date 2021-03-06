#!/usr/bin/perl
use strict;
use warnings;

my $sum = 0;
my $N = 0;
my @X;
my $SS = 0;
my $avg;
my $min = 999999;
my $max = -1;
while( my $line = <stdin> ){
     chomp $line;
     next if ($line =~ m/^[ \#]/);
     last if($line eq "");
    #print $line;
     push(@X, $line);
     $N ++;
     $sum += $line;
     if ($line > $max) {
         $max = $line;
     }
     if ($line < $min) {
         $min = $line;
     }
}
$avg = $sum/$N;
print "Mean: $avg\n";
print "Min: $min\n";
print "Max: $max\n";

foreach my $X (@X){
     $SS += ($X - $avg)**2;
}
my $sample_stdev = sqrt($SS/($N-1));
my $stdev_pop = sqrt($SS/($N));
print "Standard error of the mean: ";
print $sample_stdev/sqrt($N);
print "\n";
print "Standard deviation of the mean: ";
print $stdev_pop/sqrt($N);
print "\n";
