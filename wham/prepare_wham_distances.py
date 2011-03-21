#!/usr/bin/python

import os
import sys
import optparse
import numpy
from configobj import ConfigObj
import tempfile
import random
import subprocess

from Queue import Queue
from threading import Thread

q = Queue()
outfile_q = Queue()

def combine_metadatas(wham_dicts):
    # make a single metadatafile containing all the intermediate files
    (fd, fpath) = tempfile.mkstemp()
    sys.stderr.write("Combined metadatafile: %s\n" % fpath)
    outfile = open(fpath, 'w')
    for md in wham_dicts:
        sys.stderr.write("  Combining %s...\n" % md['metafilepath'])
        mfile = open(md['metafilepath'])
        outfile.write(mfile.read())
        mfile.close()
    outfile.close()
    combined_dict = wham_dicts[0]
    combined_dict.update({'metafilepath':fpath})
    return combined_dict

def worker():
    while True:
        item = q.get()
        try:
            run_wham(**item)
        except Exception, e:
            sys.stderr.write("\nException while running WHAM: %s\n" % e)
        q.task_done()

def run_wham(min, max, bins, metafilepath, temp=315.0, tol=0.0001, **kwargs):
    outfile = "%s_wham.out" % metafilepath
    command = "wham %f %f %d %f %f 0 %s %s" % (min, max, bins, tol, temp, metafilepath, outfile)
    p = subprocess.Popen(command, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdoutdata, stderrdata) = p.communicate()
    outfile_q.put(outfile)

def process_pmf(filename):
    x = []
    y = []
    infile = open(filename, 'r')
    while infile:
        line = infile.readline().strip()
        if len(line) == 0:
            break
        elif line.startswith('#'):
            continue
        split_line = [ s.strip() for s in line.split('\t') ]
        if len(split_line) > 3 and split_line[1] != 'inf':
            x.append(float(split_line[0]))
            y.append(float(split_line[1]))
        else:
            x.append(float(split_line[0]))
            y.append(None)
    return (x,y)
    
def get_max_bin(pmf):
    maxdG = max(pmf[1])
    return pmf[0][pmf[1].index(maxdG)]

def get_min_bin(pmf):
    mindG = min(pmf[1])
    return pmf[0][pmf[1].index(mindG)]

def process_config(config_file, start_index=0, end_index=None, output_dir=None, metadata_filename="wham_metadata", percent=100, random=False):
    config = ConfigObj(config_file)
    project_path = os.path.abspath(os.path.dirname(config.filename))

    data_min = None
    data_max = None
    
    if output_dir is None:
        # use a temp dir
        output_dir = tempfile.mkdtemp()
        sys.stderr.write("Creating temporary dir at %s\n" % output_dir)
    elif not output_dir.startswith('/'):
        # relative path
        output_dir = os.path.join(project_path, output_dir)
        if not os.path.exists(output_dir):
            sys.stderr.write("Creating output dir: %s" % output_dir)
            os.mkdir(output_dir)

    # open the wham metadata file for writing
    wham_metadata_file = open(os.path.join(output_dir, metadata_filename), 'w')
    wham_metadata_file.write('# WHAM metadata file generated from Python\n')
    wham_metadata_file.write('# Project Path: %s\n' % project_path)
    wham_metadata_file.write('# Config: %s\n' % config_file)
    wham_metadata_file.write('# Output Dir: %s\n' % output_dir)
    wham_metadata_file.write('# Percent Data Used: %s%%\n' % str(percent))
    wham_metadata_file.write('# Random Selection: %s\n' % str(random))
    
    # loop through replicas in the config file
    for r_id, r_config in config['replicas'].items():
        sys.stderr.write("%s " % r_id)
        
        data_file = os.path.join(project_path, r_id, 'distances')
        if not os.path.exists(data_file):
            sys.stderr.write("Data file not found... skipping this replica\n")
            continue
        else:
            field_data = numpy.genfromtxt(data_file)

        data_min = min(field_data.min(), data_min) if data_min else field_data.min()
        data_max = max(field_data.max(), data_max) if data_max else field_data.max()
        
        # first, slice the data
        sample = field_data[start_index:end_index] if end_index else field_data[start_index:] 
        
        # determine the sample size (percent * sample)
        sample_size = int(round(float(percent)/100.0 * float(len(sample))))
        sys.stderr.write("[%d/%d] " % (len(field_data), sample_size))

        if sample_size < 30:
            sys.stderr.write("\n%s: Sample too small... skipping!\n" % r_id)
            continue
        
        if random:
            final_sample = random.sample(sample, sample_size)
        else:
            final_sample = sample[:sample_size]

        data_file_path = os.path.join(output_dir, 'wham_data_%s' % r_id)
        f = open(data_file_path, 'w')
        for d in final_sample:
            f.write('0.0    %f\n' % d)
        f.close()
        wham_metadata_file.write('%s %s %s\n' % (data_file_path, r_config['coordinate'], str(float(r_config['force']))))
    
    wham_metadata_file.close()
    sys.stderr.write('Done processing config.\n')
    return {'min':int(data_min), 'max':int(data_max), 'bins': len(config['replicas'].items())*2, 'metafilepath':os.path.join(output_dir, metadata_filename), 'tol':0.0001, 'temp':315.0}

def main():    
    usage = """
        usage: %prog [options] <config.ini> <config.ini> ...

        Prepare and run WHAM.
    """
    
    parser = optparse.OptionParser(usage)
    parser.add_option("-o", "--output-dir", dest="output_dir", default=None, help="Output directory [default: temporary dir]")
    parser.add_option("--combined", dest="combined", default=False, action="store_true", help="Combine all data [default: %default]")
    parser.add_option("--convergence", dest="convergence", default=False, action="store_true", help="Analyze convergence [default: %default]")
    parser.add_option("--error", dest="error", default=False, action="store_true", help="Analyze error [default: %default]")
    parser.add_option("-t", "--threads", dest="worker_threads", default=1, help="Number of WHAM threads to use [default: %default]")
    
    (options, args) = parser.parse_args()
    
    for config_file in args:
        if not os.path.exists(config_file):
            raise Exception("Config file not found at %s\n" % config_file)
    
    
    # start the wham threads
    sys.stderr.write("Starting %d worker threads...\n" % options.worker_threads)
    for i in range(options.worker_threads):
        t = Thread(target=worker)
        t.daemon = True
        t.start()
    
    if options.convergence:
        # 1) calculate blocks of data in sequential order for each config file
        # 2) calculate the PMFs from each block
        # 3) find the max dG and min dG for the first PMF
        # 4) plot the max dG and min dG for each PMF
        raise Exception("Convergence not implemented yet")
    elif options.error:
        # 1) calculate random blocks of data for each config file
        # 2) calculate PMFs for each block
        # 3) plot each PMF, get max/min values per bin, stdev per bin
        
        # note: ALWAYS COMBINES INPUT CONFIG FILES
        
        i=0
        nblocks = 2
        
        defaults = {'min':-48, 'max':0, 'bins':100}
        
        while i < nblocks:
            wham_dicts = []
            for config_file in args:
                sys.stderr.write("Processing config file: %s\n" % config_file)                
                md = process_config(config_file, percent=20, random=True)
                md.update(defaults)
                wham_dicts.append(md)
            combined_dict = combine_metadatas(wham_dicts)
            q.put(combined_dict)
            i += 1
                
        # Wait for wham to finish
        sys.stderr.write("Waiting for WHAM to complete\n")
        q.join()
        
        # process the PMFs
        error_data = {}
        try:
            outfile = outfile_q.get_nowait()
            while True:
                pmf = process_pmf(outfile)
                for x,y in zip(pmf):
                    if x not in error_data:
                        error_data[x] = [y]
                    else:
                        error_data[x].append(y)
                outfile_q.task_done()
                outfile = outfile_q.get_nowait()
        except:
            pass
            
        # now we have the combined PMF data
        (fd, fpath) = tempfile.mkstemp()
        outfile = open(fpath, 'w')
        sys.stderr.write("Writing errors\n")
        outfile.write('BIN,SEM,STDEV,MIN,MAX')
        
        for key in sorted(error_data.keys()):
            d = numpy.array(error_data[key])
            outfile.write('%f,%f,%f,%f,%f\n' % (key,numpy.sem(d),numpy.std(d),d.min(),d.max()))
        outfile.close()
        sys.stderr.write(fpath+"\n")
        
    else:
        wham_dicts = []
        for config_file in args:
            sys.stderr.write("Processing config file: %s\n" % config_file)
            wham_dict = process_config(config_file)
            wham_dicts.append(wham_dict)
            
            if not options.combined:
                # run it right away
                q.put(wham_dict)
        
        if options.combined:
            combined_dict = combine_metadatas(wham_dicts)
            q.put(combined_dict)
            
        # Wait for wham to finish
        sys.stderr.write("Waiting for WHAM to complete\n")
        q.join() 
    
        try:
            outfile = outfile_q.get_nowait()
            while True:
                print outfile
                outfile_q.task_done()
                outfile = outfile_q.get_nowait()
        except:
            # queue empty
            pass


if __name__=='__main__':
    main()
