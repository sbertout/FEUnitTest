import os, sys, argparse, json, shutil, collections
import FabricEngine.Core as FECore
from subprocess import Popen, PIPE, STDOUT

testRootDir = '.kltest'

class KLObject:
	def __init__(self, name, parentObjectName):
		self.name = name
		self.parentObjectNames = parentObjectName
		self.methods = []
	def addMethod(self, methodName):
		self.methods.append(methodName)
	def getMethods(self):
		return self.methods
	def getTestMethods(self):
		testMethods = []
		for method in self.methods:
			if method.startswith('test'): testMethods.append(method)
		testMethods.sort()
		return testMethods
	def inheritsFromTestCase(self, klObjects):
		inheritsFromTestCase = 'TestCase' in self.parentObjectNames
		if inheritsFromTestCase == False:
			for parentObjectName in self.parentObjectNames:
				if parentObjectName in klObjects and klObjects[parentObjectName].inheritsFromTestCase(klObjects):
					inheritsFromTestCase = True
		return inheritsFromTestCase
	def canBeTested(self, klObjects):
		inheritsFromTestCase = self.inheritsFromTestCase(klObjects)
		if inheritsFromTestCase == False:
			return False
		nbTestMethod = 0
		for method in self.methods:
			if str(method.lower()).startswith('test'): nbTestMethod += 1
		return nbTestMethod > 0

def rmTestRootDir():
	if os.path.exists(testRootDir): 
		shutil.rmtree(testRootDir, ignore_errors=True)

def initTestRootDir():
	rmTestRootDir()
	os.makedirs(testRootDir)

def findKLFiles(rootDir, mask):
	klFiles = []
	for dirName, subdirList, fileList in os.walk(rootDir):
	    for fname in fileList:
	    	lfname = fname.lower()
	        if lfname.endswith('.kl'):
	        	if mask != '' and mask not in lfname:
	        		continue
	        	klFiles.append(os.path.join(dirName, lfname))
	return klFiles

def generateKLFilesToTest(klFiles):
	klTestFiles = []
	c = FECore.createClient()
	for klFile in klFiles:
		file = open(klFile, 'r')
		sourceCode = file.read()
		file.close()
		ast = c.getKLJSONAST('AST.kl', sourceCode, False)
		data = json.loads(ast.getStringCString())['ast']

		klObjects = {}
		for elementList in data:
		    type = elementList['type']
		    if type == 'ASTObjectDecl':
		        objectName = elementList['name']
		        parentObjectName = [] if 'parentsAndInterfaces' not in elementList else elementList['parentsAndInterfaces']
		        klObjects[objectName] = KLObject(objectName, parentObjectName)
		    elif type == 'MethodOpImpl':
		        klObjects[elementList['thisType']].addMethod(elementList['name'])	

		ordererdKlObjects = collections.OrderedDict(sorted(klObjects.items(), key=lambda t: t[0]))
		ignoreThisTest = True
		for klObjectName in ordererdKlObjects:
			klObject = ordererdKlObjects[klObjectName]
			if klObject.canBeTested(ordererdKlObjects):
				ignoreThisTest = False
		if ignoreThisTest: continue

		klTmpFilePrefix = testRootDir + '/kltest_'
		newFileName = klTmpFilePrefix + klFile.replace('/', '_').replace('.', '_')
		newFile = open(newFileName, 'w')
		newFile.write(sourceCode)

		newFile.write('operator entry() { \n')
		newFile.write('\tSize testCount = 0; Size invalidTestCount = 0; report("Processing %s.."); \n' % os.path.splitext(os.path.basename(klFile))[0])
		for klObjectName in ordererdKlObjects:
			klObject = ordererdKlObjects[klObjectName]
			if klObject.canBeTested(ordererdKlObjects):
				newFile.write('\n\treport(" - %s: %s");\n' % (klObjectName, ', '.join(klObject.getTestMethods())))
				newFile.write('\tinvalidTestCount += %s().setOutFile("%s")\n' % (klObjectName, klFile.replace('.kl', '.out')))
				for method in klObject.getTestMethods():
					newFile.write('\t.setUp().%s().tearDown()\n' % method)
				newFile.write('\t.isValid() ? 0 : 1; testCount ++;\n')
		newFile.write('\n\tif (invalidTestCount == 0) report("Ran " + testCount + " test case(s).. OK!" + "\n");\n')
		newFile.write('\telse report("Failed test case(s) " + invalidTestCount + "/" + testCount + "\n");\n')
		newFile.write('}')
		newFile.close()
		klTestFiles.append(newFileName)
	return klTestFiles

def execKL(klFile):
	print 'Testing ' + klFile
	output = Popen('kl ' + klFile, shell=True, stdin=PIPE, stdout=PIPE, stderr=STDOUT, close_fds=True).stdout.read()
	if args.quiet == False: print output
	errorCount = output.count('KL stack trace:')
	if errorCount > 0:
		if args.quiet: print output
		print '%s Error(s) found!!\n' % errorCount
	return errorCount > 0#	returnCode = 1

parser = argparse.ArgumentParser(description='Run KL test files')
parser.add_argument('-q', '--quiet', action="store_true", default=False, help='quiet mode')
parser.add_argument('-c', '--consolidate', action="store_true", default=False, help='consolidate KL files into a master one to run single kl command')
parser.add_argument('-d', '--debugMode', action="store_true", default=False, help='Debug mode: generated kl files wont be deleted')
parser.add_argument('-m', '--mask', action="store", default='', help='mask KL test files')
parser.add_argument('-r', '--rootDir', action="store", default='.', help='search for KL test files from the specified rootDir')
args = parser.parse_args()

returnCode = 0
initTestRootDir()
klFiles = findKLFiles(args.rootDir, args.mask)
klFilesToTest = generateKLFilesToTest(klFiles)
if args.consolidate:
	consolidatedKLFileName = testRootDir + '/kltest_consolidated.kl'
	consolidatedKLFile = open(consolidatedKLFileName, 'w')
	funcs = []
	for klFileToTest in klFilesToTest:
		klFileBase = os.path.splitext(os.path.basename(klFileToTest))[0]
		funcs.append(klFileBase)
		klFile = open(klFileToTest, 'r')
		klFileContent = klFile.read()
		klFile.close()
		klFileContent = klFileContent.replace('operator entry', klFileBase)
		consolidatedKLFile.write(klFileContent + '\n\n')
	consolidatedKLFile.write('operator entry() {\n')
	for func in funcs:
		consolidatedKLFile.write('\t%s();\n' % func)
	consolidatedKLFile.write('}\n')
	consolidatedKLFile.close()
	returnCode |= execKL(consolidatedKLFileName)
else:
	if args.quiet == False: print '\n'
	for klFileToTest in klFilesToTest:
		returnCode |= execKL(klFileToTest)
if args.debugMode == False: rmTestRootDir()
if args.quiet and returnCode == 0: print 'OK!'
sys.exit(returnCode)
