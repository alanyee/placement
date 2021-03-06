import TimedExec
from IDPLException import *
import os
import time
import socket
import sys
import signal
import hashlib

timeoutDefault = 30
portArgDefault = "-p"
class DataMover(object):
	def __init__(self,timeout=timeoutDefault):
		self.timeout = timeout
		self.lowPort = None 
		self.highPort = None 
		self.exe = ""
		self.args = []
		self.portArg = portArgDefault
		self.port = 0
		self.portReporter = Reporter().noReport
		self.inputFile = None
		self.outputFile = None

	def setPortRange(self,low,high):
		self.lowPort = low
		self.highPort = high
	
	def getPortRange(self,low,high):
		return (self.lowPort, self.highPort)

	def setPortArg(self,portArg):
		self.portArg = portArg 

	def setExe(self, executable):
		self.exe = executable

	def setArgs(self,args):
		self.args = args 

	def setOutputHandler(self,stdout=None):
		self.stdoutHandler = stdout 

	def setErrHandler(self,stderr=None):
		self.stderrHandler = stderr 

	def setInputFile(self,fname):
		self.inputFile = fname

	def setOutputFile(self,fname):
		self.outputFile = fname

	def setPortReporter(self,reporter):
		""" enable the port actually used by the server to be reported """
		self.portReporter = reporter

	def setTimeout(self,timeout):
		self.timeout = timeout

	def md5(self,fname):
		"""Open the file fname, read it and calc md5sum"""
		buflen = 65536
		hash = hashlib.md5()
		with open(fname,'r',buflen) as f:
			buf = f.read(buflen)
			while len(buf) > 0:
				hash.update(buf)
				buf = f.read(buflen)
		return hash.hexdigest()

	
	def run(self):

		if self.inputFile is not None:
			iFile = file(self.inputFile,'r')
		else:
			iFile = None

		if self.lowPort is None or self.highPort is None:
			targs=[self.exe]
			targs.extend(self.args)
			resultcode,output,err=TimedExec.runTimedCmd(self.timeout,
				targs, indata=iFile,
				outhandler=self.stdoutHandler, 
				errhandler=self.stderrHandler)
			if resultcode < 0:
				sys.stdout.write("Result code: %d\n" % resultcode)
				if iFile is not None:
					iFile.close()
				raise TimeOutException(self.exe)	
		else:
			for self.port in range(self.lowPort,self.highPort):
				try:
					targs=[self.exe]
					targs.extend(self.args)
					targs.extend([self.portArg, "%d" % int(self.port)]),
					## in 2 seconds call the portReporter to indicate
					## which port is being used. If specific mover has
					## an error within 2 seconds, assumed that port is in use.
					## Then next port is tried.
					rd = TimedExec.RunDelayed(2,self.portReporter,self.port)
					rd.run()
					resultcode,output,err=TimedExec.runTimedCmd(self.timeout,
						targs, indata=iFile,
						outhandler=self.stdoutHandler, 
						errhandler=self.stderrHandler)
					rd.join()
					if resultcode < 0:
						sys.stdout.write("Result code: %d\n" % resultcode)
						raise TimeOutException(self.exe)	
					break
				except PortInUseException,e:
					## Cancel the portReporter
					rd.cancel()
					sys.stderr.write(e.message + "\n")
					rd.join()

			if iFile is not None:
				iFile.close()


class Iperf(DataMover):

	def __init__(self):
		super(Iperf,self).__init__()
		iperfExe = '/usr/bin/iperf'
		if not os.path.exists(iperfExe):
			iperfExe = '/opt/iperf/bin/iperf'
		self.setExe(iperfExe)
		self.setOutputHandler(self.iperfout)
		self.setErrHandler(self.iperferr)
		self.rawData = None
		self.transferredKB=0
	
	def iperfout(self,pid,str):
		""" stdout handler when running iperf under TimedExec """
		message = "%s(%d): %s" % (socket.getfqdn(),pid,str)
		sys.stdout.write(message)
		host = socket.getfqdn()

		try:
			## if transfer finished, record bytes sent
			## Then kill iperf (server)
			if str.find("its/sec") != -1:
				self.transferredKB = str.split()[-4]
				self.rawData = " ".join(str.split()[-2:])
				os.kill(pid,signal.SIGTERM)
				sys.stdout.write("Killing pid %d\n" % pid)
		except IDPLException,e:
			sys.stderr.write(e.message)

	def iperferr(self,pid,str):
		""" stderr handler when running iperf under TimedExec """
		sys.stderr.write("%d#: %s" %(pid,str))
		if str.find("bind failed") != -1:
			raise PortInUseException("iperf", self.port)

	def client(self,server,port=5001):
		self.setArgs(["-c","%s" % server,"-p","%d" % int(port),"-f","k"])
		self.run()

	def server(self):
		self.setArgs(["-s"])
		self.setPortRange(5001,5010)
		self.run()

class Netcat(DataMover):
	""" Netcat-based Data Mover """
	def __init__(self):
		super(Netcat,self).__init__()
		self.setExe('/usr/bin/nc')
		self.setOutputHandler(self.netcatout)
		self.setErrHandler(self.netcaterr)
		self.oFile = None	

	def setOutputFile(self,fname):
		super(Netcat,self).setOutputFile(fname)
		self.oFile = file(self.outputFile,"w")	
		self.setOutputHandler(self.oFile)

	def netcatout(self,pid,str):
		""" stdout handler when running netcat under TimedExec """
		message = "%s(%d): %s" % (socket.getfqdn(),pid,str)
		sys.stdout.write(str)

	def netcaterr(self,pid,str):
		""" stderr handler when running netcat under TimedExec """
		sys.stdout.write("%d#: %s" %(pid,str))
		raise PortInUseException("netcat", self.port)

	def client(self,server,port=5011):
		self.setArgs(["%s" % server,"%d" % int(port)])
		self.run()
		if self.oFile is not None:
			self.oFile.close()

	def server(self):
		self.setArgs(["-d"])
		self.setPortArg("-l")
		self.setPortRange(5011,5020)
		self.run()
		if self.oFile is not None:
			self.oFile.close()

class Reporter(object):
	""" Empty portReport. Nothing is printed """
	def noReport(self, port):
		pass

class PrintReporter(object):
	""" print the port to stdout """
	def doReport(self, port):
		print port	

# vim: ts=4:sw=4:
