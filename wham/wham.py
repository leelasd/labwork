#!/usr/bin/python

import os
import sys
import optparse
import numpy
from configobj import ConfigObj
import tempfile
import random
import datetime

from Queue import Queue
from threading import Thread

from pmf import process_pmf, dG_bind, dG, run_wham


q = Queue()
outfile_q = Queue()

def combine_metadatas(wham_dicts):
    if len(wham_dicts) == 1:
        return wham_dicts[0]
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
            outfile = run_wham(**item)
        except Exception, e:
            sys.stderr.write("\nException while running WHAM: %s\n" % e)
        item['outfile'] = outfile
        outfile_q.put(item)
        q.task_done()
        
def write_datasets(datasets, output_dir=None, header={}):
    if output_dir is None:
        # use a temp dir
        output_dir = tempfile.mkdtemp()
        sys.stderr.write("Creating temporary dir at %s\n" % output_dir)
    elif not os.path.exists(output_dir):
        sys.stderr.write("Creating output dir: %s" % output_dir)
        os.mkdir(output_dir)
    
    metadata_path = os.path.join(output_dir, 'metadata')
    metadata_file = open(metadata_path, 'w')
    metadata_file.write('# WHAM metadata file generated from Python\n')
    metadata_file.write('# %s\n' % datetime.datetime.now().isoformat())
    for k,v in header.items():
        metadata_file.write('# %s: %s\n' % (k,v))
    
    keys = []
    for dataset in datasets:
        for k,v in dataset.items():
            if k in keys:
                sys.stderr.write('\nWARNING: Key for dataset %s is not unique... modifying name.\n' % k)
                k = k+'_'
            keys.append(k)
            data_file_path = os.path.join(output_dir, 'data_%s' % k)
            f = open(data_file_path, 'w')
            for d in v['data']:
                f.write('0.0    %f\n' % d)
            f.close()
            metadata_file.write('%s %s %s\n' % (data_file_path, v['coordinate'], v['force']))
    return metadata_path    

def process_config2(config_file, options, output_dir=None, start_index=0, end_index=None, percent=100, randomize=False):
    config = ConfigObj(config_file)
    project_path = os.path.abspath(os.path.dirname(config.filename))

    dataset = {}
    prefix = config['title']

    # loop through replicas in the config file
    for r_id, r_config in config['replicas'].items():
        sys.stderr.write("%s " % r_id)

        data_file = os.path.join(project_path, r_id, options.data_file)
        
        if not os.path.exists(data_file):
            sys.stderr.write("Data file not found... skipping this replica\n")
            continue
        else:
            field_data = numpy.genfromtxt(data_file)

        if len(field_data) < 50:
            sys.stderr.write("\n%s: Sample too small... skipping!\n" % r_id)
            continue

        # first, slice the data
        sample = field_data[start_index:end_index] if end_index else field_data[start_index:]
        
        if end_index is not None and len(sample) < (end_index-start_index):
            sys.stderr.write("\nNot enough samples (%d) for start/end (%d) index slice\n" % (len(sample), end_index-start_index))
            return False

        # determine the sample size (percent * sample)
        sample_size = int(round(float(percent)/100.0 * float(len(sample))))
        sys.stderr.write("[%d/%d] " % (len(field_data), sample_size))

        if randomize:
            final_sample = random.sample(field_data, sample_size)
        else:
            final_sample = sample[:sample_size]

        dataset[prefix+r_id] = {'data': numpy.array(final_sample), 'coordinate': r_config['coordinate'], 'force': r_config['force']}
        
    sys.stderr.write('Done processing config.\n')
    return dataset

def process_config(config_file, options, start_index=0, end_index=None, output_dir=None, metadata_filename="wham_metadata", percent=100, randomize=False):
    config = ConfigObj(config_file)
    project_path = os.path.abspath(os.path.dirname(config.filename))
    
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
    wham_metadata_file.write('# Random Selection: %s\n' % str(randomize))
    
    dataset = {}
    
    # loop through replicas in the config file
    for r_id, r_config in config['replicas'].items():
        sys.stderr.write("%s " % r_id)
        
        data_file = os.path.join(project_path, r_id, options.data_file)
        if not os.path.exists(data_file):
            sys.stderr.write("Data file not found... skipping this replica\n")
            continue
        else:
            field_data = numpy.genfromtxt(data_file)

        # first, slice the data
        sample = field_data[start_index:end_index] if end_index else field_data[start_index:]
        
        # determine the sample size (percent * sample)
        sample_size = int(round(float(percent)/100.0 * float(len(sample))))
        sys.stderr.write("[%d/%d] " % (len(field_data), sample_size))

        if sample_size < 30:
            sys.stderr.write("\n%s: Sample too small... skipping!\n" % r_id)
            continue
        
        if randomize:
            final_sample = random.sample(field_data, sample_size)
        else:
            final_sample = sample[:sample_size]

        dataset[r_id] = {'data': numpy.array(final_sample), 'coordinate': r_config['coordinate'], 'force': r_config['force']}
        
        data_file_path = os.path.join(output_dir, 'wham_data_%s' % r_id)
        f = open(data_file_path, 'w')
        for d in final_sample:
            f.write('0.0    %f\n' % d)
        f.close()
        wham_metadata_file.write('%s %s %s\n' % (data_file_path, r_config['coordinate'], str(float(r_config['force']))))
    
    wham_metadata_file.close()
    sys.stderr.write('Done processing config.\n')
    return {'metafilepath':os.path.join(output_dir, metadata_filename)}

def main():    
    usage = """
        usage: %prog [options] <config.ini> <config.ini> ...

        Prepare and run WHAM.
    """
    
    parser = optparse.OptionParser(usage)
    parser.add_option("-o", "--output-dir", dest="output_dir", default=None, help="Output directory [default: temporary dir]")
    parser.add_option("-p", "--output-pmf", dest="output_pmf", default=None, help="Output PMF file [default: temporary file]")
    parser.add_option("--convergence", dest="convergence", default=False, help="Analyze convergence [default: %default]")
    parser.add_option("--conv-x", dest="convergence_x", tyle="float", default=25, help="Convergence of this reaction coordinate [default: %default]")    
    parser.add_option("--conv-block-size", dest="convergence_block_size", type="float", default=80, help="Convergence block size [default: %default]")    
    parser.add_option("--conv-shift", dest="convergence_shift", type="float", default=40, help="Convergence shift size [default: %default]")    
    parser.add_option("--percentage", dest="percentage", type="int", default=25, help="Percentage of data for block size [default: %default]")    
    parser.add_option("--error", dest="error", type="int", default=0, help="Analyze error by block averaging [default: %default]")
    parser.add_option("--autoshift", dest="autoshift", default=True, action="store_false", help="Auto-shift PMF [default: %default]")
    parser.add_option("-t", "--threads", dest="worker_threads", type="int", default=1, help="Number of WHAM threads to use [default: %default]")
    parser.add_option("--wham-min", dest="wham_min", type="float", default=-48, help="Minimum bin value for WHAM [default: %default]")
    parser.add_option("--wham-max", dest="wham_max", type="float", default=0, help="Maximum bin value for WHAM [default: %default]")
    parser.add_option("--wham-bins", dest="wham_bins", type="int", default=200, help="Number of bins for WHAM [default: %default]")
    parser.add_option("--wham-tol", dest="wham_tol", type="float", default=0.0001, help="Tolerance for WHAM [default: %default]")
    parser.add_option("--wham-temp", dest="wham_temp", type="float", default=323.15, help="Temperature for WHAM [default: %default]")
    parser.add_option("--start-index", dest="start_index", type="int", default=0, help="Start index for data selection [default: %default]")
    parser.add_option("-d", "--data-file", dest="data_file", default="distances", help="Replica data file name [default: %default]")
    
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
            
    wham_defaults = {'min':options.wham_min, 'max':options.wham_max, 'bins':options.wham_bins, 'tol':options.wham_tol, 'temp':options.wham_temp}
    
    if options.convergence:
        # note: ALWAYS COMBINES INPUT CONFIG FILES
        
        # 1) calculate blocks of data in sequential order for each config file
        #       block size is 10% of the max n
        # 2) calculate the PMFs from each block
        # 3) calculate some value from each PMF (dG_bind)
        # 4) print <block>,<value> to plot
        
        block_size = options.convergence_block_size
        shift = options.convergence_shift
        start_index = 0
        done = False
        while not done:
            end_index = start_index+block_size
            sys.stderr.write("Extracting block from %d to %d...\n" % (start_index, end_index))
            
            datasets = []
            for config_file in args:
                dataset = process_config2(config_file, options, start_index=start_index, end_index=start_index+block_size)
                # TODO: this is bad
                if not dataset:
                    done = True
                    break
                else:
                    datasets.append(dataset)

            if not done:
                metadata_file = write_datasets(datasets)
                wham_dict = wham_defaults.copy()
                wham_dict.update({'metafilepath': metadata_file, 'start_index':start_index, 'end_index':end_index})
                q.put(wham_dict)
                start_index += shift
        
        sys.stderr.write("Waiting for WHAM to complete\n")
        q.join()
        
        # process the PMFs        
        item = outfile_q.get_nowait()
        results = {}
        pmfs = {}
        while True:
            outfile = item['outfile']
            #sys.stderr.write("Processing WHAM outfile: %s\n" % outfile)
            pmf = process_pmf(outfile, shift=options.autoshift)
            pmfs[item['start_index']] = pmf
            # correction = dG_bind(pmf, imin=-32, imax=-22)
            #correction = 0.0
            # print "%d,%0.5f" % (item['start_index'],item['end_index'],dG_bind(pmf, imin=-32, imax=-22)-correction)
            #results[item['start_index']] = dG_bind(pmf, imin=-32, imax=-19)-correction
            results[item['start_index']] = dG(pmf, options.convergence_x)
            outfile_q.task_done()
            try:
                item = outfile_q.get_nowait()
            except:
                sys.stderr.write("All outfiles processed...\n")
                break
        for k in sorted(results.keys()):
            print "%d,%0.5f" % (k,results[k])
        
        # write PMFs        
        if options.output_pmf:
            fpath = options.output_pmf
        else:
            (fd, fpath) = tempfile.mkstemp()
        
        outfile = open(fpath, 'w')
        sys.stderr.write("Writing PMFs to %s\n" % fpath)
        pmf_bins = {}
        pmf_titles = []
        for p in sorted(pmfs.keys()):
            pmf_titles.append(str(p))
            for x,y in pmfs[p]:
                if x not in pmf_bins:
                    pmf_bins[x] = [y]
                else:
                    pmf_bins[x].append(y)

        outfile.write('BIN,MEAN,SEM,STDEV,MIN,MAX,%s\n' % (','.join(pmf_titles)))
        for bin in sorted(pmf_bins.keys()):
            pmf_values = ','.join([ str(v) for v in pmf_bins[bin] ])
            d = numpy.array(pmf_bins[bin])
            sem = numpy.std(d, ddof=1)/numpy.sqrt(d.size)
            outfile.write('%f,%f,%f,%f,%f,%f,%s\n' % (bin, d.mean(), sem, numpy.std(d), d.min(), d.max(), pmf_values))
        outfile.close()

    elif options.error > 0:
        # note: ALWAYS COMBINES INPUT CONFIG FILES
        
        # 1) calculate random blocks of data for each config file
        # 2) calculate PMFs for each block
        # 3) plot each PMF, get max/min values per bin, stdev per bin
        
        i=0        
        while i < options.error:
            wham_dicts = []
            for config_file in args:
                sys.stderr.write("Processing config file: %s\n" % config_file)                
                md = process_config(config_file, options, percent=options.percentage, randomize=True, start_index=options.start_index)
                md.update(wham_defaults)
                wham_dicts.append(md)
            combined_dict = combine_metadatas(wham_dicts)
            q.put(combined_dict)
            i += 1
                
        # Wait for wham to finish
        sys.stderr.write("Waiting for WHAM to complete\n")
        q.join()
        
        # process the PMFs
        error_data = {}
        item = outfile_q.get_nowait()
        while True:
            outfile = item['outfile']
            
            sys.stderr.write("Processing WHAM outfile: %s\n" % outfile)
            pmf = process_pmf(outfile, shift=options.autoshift)            
            for x,y in pmf:
                if x not in error_data:
                    error_data[x] = [y]
                else:
                    error_data[x].append(y)
            outfile_q.task_done()
            try:
                item = outfile_q.get_nowait()
            except:
                sys.stderr.write("All outfiles processed...\n")
                break

        # now we have the combined PMF data
        if options.output_pmf:
            fpath = options.output_pmf
        else:
            (fd, fpath) = tempfile.mkstemp()

        outfile = open(fpath, 'w')
        sys.stderr.write("Writing errors\n")
        outfile.write('BIN,MEAN,SEM,STDEV,MIN,MAX\n')
        for key in sorted(error_data.keys()):
            d = numpy.array(error_data[key])
            sys.stderr.write("%0.2f,%d " % (key, d.size))
            sem = numpy.std(d, ddof=1)/numpy.sqrt(d.size)
            outfile.write('%f,%f,%f,%f,%f,%f\n' % (key,d.mean(),sem,numpy.std(d),d.min(),d.max()))
        outfile.close()
        sys.stderr.write("\n"+fpath+"\n")
        
    else:
        # standard procedure
        # does not combine files
        
        # for each config file, send it to wham
        for config_file in args:
            sys.stderr.write("Processing config file: %s\n" % config_file)                
            md = process_config(config_file, options, percent=options.percentage, randomize=True, start_index=options.start_index)
            md.update(wham_defaults)
            q.put(md)
                            
        # Wait for wham to finish
        sys.stderr.write("Waiting for WHAM to complete\n")
        q.join() 
    
    
        # process the PMFs
        error_data = {}
        item = outfile_q.get_nowait()
        while True:
            outfile = item['outfile']
            sys.stderr.write("Processing WHAM outfile: %s\n" % outfile)
            pmf = process_pmf(outfile, shift=options.autoshift)            
            for x,y in pmf:
                if x not in error_data:
                    error_data[x] = [y]
                else:
                    error_data[x].append(y)
            outfile_q.task_done()
            try:
                item = outfile_q.get_nowait()
            except:
                sys.stderr.write("All outfiles processed...\n")
                break
    
        # now we have the combined PMF data
        if options.output_pmf:
            fpath = options.output_pmf
        else:
            (fd, fpath) = tempfile.mkstemp()

        outfile = open(fpath, 'w')
        
        sys.stderr.write("Writing errors\n")
        outfile.write('BIN,MEAN,SEM,STDEV,MIN,MAX\n')
        for key in sorted(error_data.keys()):
            d = numpy.array(error_data[key])
            sys.stderr.write("%0.2f,%d " % (key, d.size))
            sem = numpy.std(d, ddof=1)/numpy.sqrt(d.size)
            outfile.write('%f,%f,%f,%f,%f,%f\n' % (key,d.mean(),sem,numpy.std(d),d.min(),d.max()))
        outfile.close()
        sys.stderr.write("\n"+fpath+"\n")


if __name__=='__main__':
    main()
