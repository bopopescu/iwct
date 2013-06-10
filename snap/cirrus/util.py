#!/usr/bin/python

from snap.boto import ec2
from snap.boto import exception
from snap.boto.ec2 import connection
from snap.pyglog import *
import urllib2
import socket
import os
import multiprocessing
import subprocess
import sys
import time

import math

#import shlex

import tempfile
import paramiko
import StringIO

################################################################################
# Ansible Helpers    
################################################################################

from snap import ansible
from snap.ansible import callbacks
from snap.ansible import playbook
from snap.ansible import utils
from snap.ansible import inventory
from snap.ansible.utils import plugins

def RunPlaybookOnHost(playbook_path, host, private_key, extra_vars = None):
  inventory = ansible.inventory.Inventory([host])
  if len(inventory.list_hosts()) == 0:
    LOG(FATAL, "provided hosts list is empty")
  stats = callbacks.AggregateStats()
  playbook_cb = ansible.callbacks.PlaybookCallbacks(verbose=ansible.utils.VERBOSITY)
  runner_cb = ansible.callbacks.PlaybookRunnerCallbacks(stats, verbose=ansible.utils.VERBOSITY)
  pb = ansible.playbook.PlayBook(playbook=playbook_path,
                            host_list = [host],
                            remote_user = 'ubuntu',
                            private_key_file = None,
                            private_key = private_key,
                            stats = stats,
                            callbacks = playbook_cb,
                            runner_callbacks = runner_cb,    
                            extra_vars = extra_vars                        
                            )
  results = pb.run()
  print results
  
  if 'dark' in results:
    if len(results['dark']) > 0:
        print "Contact failures:"
        for host, reason in results['dark'].iteritems():
            print "  %s (%s)" % (host, reason['msg'])
        return False
      
  return True



################################################################################
# Local Helpers    
################################################################################

def ExecuteCmd(cmd, quiet=False):
  result = None
  if quiet:    
    with open(os.devnull, "w") as fnull:    
      result = subprocess.call(cmd, shell=True, stdout = fnull, stderr = fnull)
  else:
    result = subprocess.call(cmd, shell=True)
  return result



def CheckOutput(*popenargs, **kwargs):
  r"""Run command with arguments and return its output as a byte string.
  Backported from Python 2.7 as it's implemented as pure python on stdlib.
  >>> check_output(['/usr/bin/python', '--version'])
  Python 2.6.2
  """
  process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
  output, unused_err = process.communicate()
  retcode = process.poll()
  if retcode:
      cmd = kwargs.get("args")
      if cmd is None:
          cmd = popenargs[0]
      error = subprocess.CalledProcessError(retcode, cmd)
      error.output = output
      raise error
  return retcode, output    


def UrlGet(url, timeout=10, retries=0):
  """
  Retrieve content from the given URL.
  """
   # in Python 2.6 we can pass timeout to urllib2.urlopen
  socket.setdefaulttimeout(timeout)
  attempts = 0
  while True:
    try:
      return urllib2.urlopen(url).read()
    except urllib2.URLError:
      attempts = attempts + 1
      if attempts > retries:
        raise
      

################################################################################
# Remote SSH Helpers    
################################################################################

#def MakeSshCmd(host, private_key_file):
#  # Note: We need a large timeout, because sometimes we restart sshd and then execute a remote command... without timeout... we would need to retry all ssh commands... which we don't currently do
#  ssh_options = '-i %s -o StrictHostKeyChecking=no -o ConnectTimeout=30' % (private_key_file)
#  return 'ssh %s ubuntu@%s' % (ssh_options, host)
#
#
#def MakeScpCmd(local_filename, dest, hostname, private_key_file):
#  # Note: We need a large timeout, because sometimes we restart sshd and then execute a remote command... without timeout... we would need to retry all ssh commands... which we don't currently do
#  ssh_options = '-i %s -o StrictHostKeyChecking=no -o ConnectTimeout=30' % (private_key_file)
#  return 'scp -r %s %s ubuntu@%s:%s' % (ssh_options, local_filename, hostname, dest)
#
#  
#def MakeRemoteExecuteCmd(cmd, host, private_key_file, wait=True):
#  wait_str = ' &'
#  if wait:
#    wait_str = ' ;'  
#  cmd = '%s "%s" %s ' % (MakeSshCmd(host, private_key_file), cmd, wait_str)
#  return cmd


#def MakeCopyToHostCmd( local_filename, dest, hostname, private_key_file):
#  cmd = MakeScpCmd(local_filename, dest, hostname, private_key_file)
#  return cmd 

  
#def CopyToHosts(local_filename, dest, hostnames, private_key_file):
#  num_hosts = len(hostnames)
#  if num_hosts == 0:
#    return
#  p = multiprocessing.Pool(num_hosts)
#  pool_commands = [MakeCopyToHostCmd(local_filename, dest, hostname, private_key_file) for hostname in hostnames]    
#  p.map(ExecuteCmd, pool_commands)    
#  p.close()
#  p.join()
#  return

#def CopyToHost(local_filename, dest, hostname, ssh_key): 
#  hostnames = [hostname]     
#  CopyToHosts(local_filename, dest, hostnames, ssh_key)
#  return


def RemoteExecuteCmd(args):  
  """ Executes a command via ssh and sends back the exit status code. """
  cmd, hostname, ssh_key = args
  private_key = paramiko.RSAKey.from_private_key(StringIO.StringIO(ssh_key))
  client = paramiko.SSHClient()
  client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  
  while True:
    try:
      client.connect(hostname, username='ubuntu', pkey=private_key, allow_agent=False, look_for_keys=False)
      break
    except socket.error as e:
      print 'socket timed out...'
      time.sleep(5)
    except paramiko.AuthenticationException as e:
      print e
      time.sleep(5) 
    
  channel = client.get_transport().open_session()
  channel.exec_command(cmd)
  exit_code = channel.recv_exit_status()
  output = channel.recv(1000000)
  client.close()
  return exit_code, output
  
  
def RunCommandOnHosts(cmd, hostnames, ssh_key):
  if not hostnames:
    return    
  p = multiprocessing.Pool(len(hostnames))
  #pool_commands = [MakeRemoteExecuteCmd(cmd, hostname, private_key_file, wait=wait) for hostname in hostnames]
  remote_command_args = [(cmd, hostname, ssh_key) for hostname in hostnames]
  result = None
  try: 
    #result = p.map(ExecuteCmd, pool_commands)
    result = p.map(RemoteExecuteCmd, remote_command_args)
  except:
    LOG(INFO, 'failure in RunCommandOnHosts...')
    raise
  p.close()
  p.join()
  return result    

def RunCommandOnHost(cmd, hostname, ssh_key):
  hostnames = [hostname]  
  results = RunCommandOnHosts(cmd, hostnames, ssh_key)  
  CHECK_EQ(len(results), 1)    
  return results[0]


def ReadRemoteFile(remote_file_path, hostname, ssh_key):  
  cmd = 'cat %s' % remote_file_path
  exit_code, output = RunCommandOnHost(cmd, hostname, ssh_key)
  return output


#def FileExists(remote_file_path, hostname, ssh_key):
#  CHECK(remote_file_path)
#  cmd = 'ls %s' % remote_file_path
#  remote_cmd = MakeRemoteExecuteCmd(cmd, hostname, ssh_key, wait=True)
#  output = None
#  try:
#    retcode, output = CheckOutput(remote_cmd, shell=True)  
#    #CHECK_EQ(retcode, 0)
#  except subprocess.CalledProcessError as e:
#    pass
#  exists = False  
#  if output != None:
#    output = output.strip()
#    if output == remote_file_path:
#      exists = True
#  return exists


#def RunScriptOnHosts(local_path_to_script, script_args, hostnames, private_key_file):  
#  CHECK(os.path.exists(local_path_to_script), 'Script file does not exist: %s' % (local_path_to_script))
#  CopyToHosts(local_path_to_script, "", hostnames, private_key_file)
#  remote_path_to_script = "./"+ os.path.basename(local_path_to_script)
#  retvals = RunCommandOnHosts("chmod +x " + remote_path_to_script, hostnames, private_key_file)
#  retvals = RunCommandOnHosts("sudo " + remote_path_to_script + " " + script_args, hostnames, private_key_file)
#  CHECK_EQ(len(retvals), len(hostnames))
#  success_flags = [(r == 0) for r in retvals ]
#  return success_flags
#
#def RunScriptOnHost(local_path_to_script, script_args, hostname, private_key_file):
#  hostnames = []
#  hostnames.append(hostname)
#  success_flags = RunScriptOnHosts(local_path_to_script, script_args, hostnames, private_key_file)
#  CHECK(len(success_flags), 1)
#  return success_flags[0]


def WaitForInstanceReachable(instance, ssh_key):
  CHECK(instance)
  hostname = instance.dns_name
  while True:
    unreachable = GetUnreachableHosts([hostname], ssh_key)
    if unreachable:
      print 'waiting for unreachable hosts: %s' % unreachable
      time.sleep(5)
    else:
      break
  return

def GetUnreachableHosts(hostnames, ssh_key):
  ssh_status = AreHostsReachable(hostnames, ssh_key)
  CHECK_EQ(len(hostnames), len(ssh_status))    
  nonresponsive_hostnames = [host for (host, ssh_ok) in zip(hostnames, ssh_status) if ssh_ok == False]
  return nonresponsive_hostnames

def GetUnreachableInstances(instances, ssh_key):
  hostnames = [i.private_ip for i in instances]
  ssh_status = AreHostsReachable(hostnames, ssh_key)
  CHECK_EQ(len(hostnames), len(ssh_status))    
  nonresponsive_instances = [instance for (instance, ssh_ok) in zip(instances, ssh_status) if ssh_ok == False]
  return nonresponsive_instances
   
def AreHostsReachable(hostnames, ssh_key):
  # validate input
  for hostname in hostnames:
    CHECK(len(hostname))
  ssh_ok = [exit_code == 0 for (exit_code, output) in RunCommandOnHosts('echo test > /dev/null', hostnames, ssh_key)]
  return ssh_ok
           
def WaitForHostsReachable(hostnames, ssh_key):
  """ ssh_key contents of the private key as a string (for DB apis)."""
  
  while True:
    unreachable = GetUnreachableHosts(hostnames, ssh_key)
    if unreachable:
      print 'waiting for unreachable hosts: %s' % unreachable
      time.sleep(5)
    else:
      break
  return

################################################################################
# EC2 Helpers    
################################################################################

def GetRegion(region_name):
  regions = ec2.regions()
  region = None
  valid_region_names = []
  for r in regions:
    valid_region_names.append(r.name)
    if r.name == region_name:
      region = r 
      break
      
  if not region:      
    LOG(INFO, 'invalid region name: %s ' % (region_name))
    LOG(INFO, 'Try one of these:\n %s' % ( '\n'.join(valid_region_names)))
    CHECK(False)
  return  region


def WaitForVolume(volume, desired_state):
  print 'Waiting for volume %s to be %s...' % (volume.id, desired_state)
  while True:
    volume.update()
    sys.stdout.write('.')
    sys.stdout.flush()
    print 'status is: %s' % volume.status
    if volume.status == desired_state:
      break
    time.sleep(5)
  print 'done'
  return


def WaitForVolumeAvailable(volume):
  WaitForVolume(volume, 'available')
  return

def WaitForVolumeAttached(volume):
  WaitForVolume(volume, 'in-use')
  return



def WaitForSnapshotCompleted(snapshot):
  print 'Waiting for snapshot %s to be completed...' % (snapshot)
  while True:
    snapshot.update()
    sys.stdout.write('.')
    sys.stdout.flush()
    print 'status is: %s' % snapshot.status
    if snapshot.status == 'completed':
      break
    time.sleep(5)
  print 'done'
  return


def __WaitForInstance(instance, desired_state):
  print 'Waiting for instance %s to change to %s' % (instance.id, desired_state)
  while True:
    instance.update()
    state = instance.state
    sys.stdout.write('.')
    sys.stdout.flush()
    if state == desired_state:
      break
    time.sleep(5)
  print 'done'
  return


def GetInstanceState(instance):
  instance.update()
  return instance.state
  

def WaitForInstanceRunning(instance):
  __WaitForInstance(instance, u'running')  
  return 

def WaitForInstanceStopped(instance):
  __WaitForInstance(instance, u'stopped')  
  return

  
def WaitForInstanceTerminated(instance):
  __WaitForInstance(instance, u'terminated')  
  return


#def CreateConnection():
#  """ Creates a connection to configured ec2 region. """
#  conf = config.GetConfiguration()  
#  conn = connection.EC2Connection(region = GetRegion(conf.region_name))
#  return conn






def NonePending(reservations):
    for res in reservations:
      for instance in res.instances:
        if instance.state == "pending":
          return False
    return True

def NumberInstancesInState(reservations, state):
  number_instances = 0
  for res in reservations:
    for instance in res.instances:
      if instance.state == state:
        number_instances += 1
  return number_instances      


#def GetUbuntuAmiForInstanceType(release_name, region_name, instance_type):
#  root_store_type, virtualization_type = GetRootStoreAndVirtualizationType(instance_type)
#  return SearchUbuntuAmiDatabase(release_name, region_name, root_store_type, virtualization_type)
  
def SearchUbuntuAmiDatabase(release_name, region_name, root_store_type, virtualization_type):
    ami_list_url = 'http://cloud-images.ubuntu.com/query/%s/server/released.txt' % (release_name)
    url_file = urllib2.urlopen(ami_list_url)
    
    release_name_col = 0
    release_tag_col = 2
    release_date_col = 3
    root_store_type_col = 4
    arch_col = 5
    region_col = 6
    ami_col = 7
        
    matching_amis = [] # list of tuples (ami_id, tokens)
    for line in url_file:
      tokens = line.split()
      
      # lines have different number of columns (one fewer for hvm)
      if (len(tokens) == 9):
        virtualization_type_col = 8
      elif (len(tokens) == 10):  
        virtualization_type_col = 9
      else:
        LOG(FATAL, 'invalid line format')
      
      if tokens[release_name_col] == release_name and tokens[release_tag_col] == 'release' and tokens[root_store_type_col] == root_store_type and tokens[arch_col] == 'amd64' and tokens[region_col] == region_name and tokens[virtualization_type_col] == virtualization_type:
        matching_amis.append((tokens[ami_col], tokens))
    matching_amis.sort(key = lambda (ami, tokens) : tokens[release_date_col], reverse=True) # order newest first
    #for matching_ami in matching_amis:
    #  print matching_ami
    #print 'selected ami: %s' % (str(matching_amis[0])) 
    CHECK_GE(len(matching_amis), 1)
    selected_ami = matching_amis[0][0]
    return selected_ami
 
 
def IsHPCInstanceType(instance_type): 
  hpc_instance_types = ['cc1.4xlarge', 'cc2.8xlarge', 'cr1.8xlarge']
  return instance_type in hpc_instance_types

def GetRootStoreAndVirtualizationType(instance_type):
    root_store_type = ''    
    if IsHPCInstanceType(instance_type):
      root_store_type = 'ebs'
      virtualization_type = 'hvm'      
    else:
      root_store_type = 'instance-store'
      virtualization_type = 'paravirtual'      
    return  root_store_type, virtualization_type  



##############################################################################
# Decorator
##############################################################################

# Retry decorator with exponential backoff
def RetryUntilReturnsTrue(tries, delay=3, backoff=2):
  '''Retries a function or method until it returns True.

  delay sets the initial delay in seconds, and backoff sets the factor by which
  the delay should lengthen after each failure. backoff must be greater than 1,
  or else it isn't really a backoff. tries must be at least 0, and delay
  greater than 0.'''

  if backoff <= 1:
    raise ValueError("backoff must be greater than 1")

  tries = math.floor(tries)
  if tries < 0:
    raise ValueError("tries must be 0 or greater")

  if delay <= 0:
    raise ValueError("delay must be greater than 0")

  def deco_retry(f):
    def f_retry(*args, **kwargs):
      mtries, mdelay = tries, delay # make mutable

      rv = f(*args, **kwargs) # first attempt
      while mtries > 0:
        if rv is True: # Done on success
          return True

        mtries -= 1      # consume an attempt
        time.sleep(mdelay) # wait...
        mdelay *= backoff  # make future wait longer

        rv = f(*args, **kwargs) # Try again

      return False # Ran out of tries :-(

    return f_retry # true decorator -> decorated function
  return deco_retry  # @retry(arg[, ...]) -> true decorator


