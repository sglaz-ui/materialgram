import os, sys, pprint, re, json, pathlib, hashlib, subprocess, glob, tempfile

executePath = os.getcwd()
sys.dont_write_bytecode = True
scriptPath = os.path.dirname(os.path.realpath(__file__))
sys.path.append(scriptPath + '/..')
import qt_version

def finish(code):
    global executePath
    os.chdir(executePath)
    sys.exit(code)

def error(text):
    print('[ERROR] ' + text)
    finish(1)

def nativeToolsError():
    error('Make sure to run from Native Tools Command Prompt.')

win = (sys.platform == 'win32')
mac = (sys.platform == 'darwin')

if win and not 'Platform' in os.environ:
    nativeToolsError()

win32 = win and (os.environ['Platform'] == 'x86')
win64 = win and (os.environ['Platform'] == 'x64')
winarm = win and (os.environ['Platform'] == 'arm64')

arch = ''
if win32:
    arch = 'x86'
elif win64:
    arch = 'x64'
elif winarm:
    arch = 'arm'
if not qt_version.resolve(arch):
    error('Usupported platform.')

qt = os.environ.get('QT')

if win and not 'COMSPEC' in os.environ:
    error('COMSPEC environment variable is not set.')

if win and not win32 and not win64 and not winarm:
    nativeToolsError()

os.chdir(scriptPath + '/../../../..')

pathSep = ';' if win else ':'
libsLoc = 'Libraries' if not win64 else (os.path.join('Libraries', 'win64'))
keysLoc = 'cache_keys'

rootDir = os.getcwd()
libsDir = os.path.realpath(os.path.join(rootDir, libsLoc))
thirdPartyDir = os.path.realpath(os.path.join(rootDir, 'ThirdParty'))
usedPrefix = os.path.realpath(os.path.join(libsDir, 'local'))

optionsList = [
    'qt6',
    'skip-release',
    'build-stackwalk',
]
options = []
runCommand = []
customRunCommand = False
for arg in sys.argv[1:]:
    if customRunCommand:
        runCommand.append(arg)
    if arg in optionsList:
        options.append(arg)
    elif arg == 'run':
        customRunCommand = True
    elif arg == 'shell':
        customRunCommand = True
        runCommand.append('shell')

if not os.path.isdir(os.path.join(libsDir, keysLoc)):
    pathlib.Path(os.path.join(libsDir, keysLoc)).mkdir(parents=True, exist_ok=True)
if not os.path.isdir(os.path.join(thirdPartyDir, keysLoc)):
    pathlib.Path(os.path.join(thirdPartyDir, keysLoc)).mkdir(parents=True, exist_ok=True)

pathPrefixes = [
    'ThirdParty\\msys64\\mingw64\\bin',
    'ThirdParty\\jom',
    'ThirdParty\\gyp',
] if win else [
    'ThirdParty/gyp',
]
pathPrefix = ''
for singlePrefix in pathPrefixes:
    pathPrefix = pathPrefix + os.path.join(rootDir, singlePrefix) + pathSep

environment = {
    'USED_PREFIX': usedPrefix,
    'ROOT_DIR': rootDir,
    'LIBS_DIR': libsDir,
    'THIRDPARTY_DIR': thirdPartyDir,
    'PATH_PREFIX': pathPrefix,
    'CMAKE_GENERATOR': 'Ninja Multi-Config',
}
if (win32):
    environment.update({
        'SPECIAL_TARGET': 'win',
        'X8664': 'x86',
    })
elif (win64):
    environment.update({
        'SPECIAL_TARGET': 'win64',
        'X8664': 'x64',
    })
elif (winarm):
    environment.update({
        'SPECIAL_TARGET': 'winarm',
        'X8664': 'ARM64',
    })
elif (mac):
    environment.update({
        'SPECIAL_TARGET': 'mac',
        'MAKE_THREADS_CNT': '-j' + str(os.cpu_count()),
        'MACOSX_DEPLOYMENT_TARGET': '10.13',
        'UNGUARDED': '-Werror=unguarded-availability-new',
        'MIN_VER': '-mmacosx-version-min=10.13',
        'CMAKE_GENERATOR': 'Ninja',
    })

ignoreInCacheForThirdParty = [
    'USED_PREFIX',
    'LIBS_DIR',
    'SPECIAL_TARGET',
    'X8664',
]

environmentKeyString = ''
envForThirdPartyKeyString = ''
for key in environment:
    part = key + '=' + environment[key] + ';'
    environmentKeyString += part
    if not key in ignoreInCacheForThirdParty:
        envForThirdPartyKeyString += part
environmentKey = hashlib.sha1(environmentKeyString.encode('utf-8')).hexdigest()
envForThirdPartyKey = hashlib.sha1(envForThirdPartyKeyString.encode('utf-8')).hexdigest()

modifiedEnv = os.environ.copy()
for key in environment:
    modifiedEnv[key] = environment[key]
if win and 'NoDefaultCurrentDirectoryInExePath' in modifiedEnv:
    del modifiedEnv['NoDefaultCurrentDirectoryInExePath']

modifiedEnv['PATH'] = environment['PATH_PREFIX'] + modifiedEnv['PATH']

def computeFileHash(path):
    sha1 = hashlib.sha1()
    with open(path, 'rb') as f:
        while True:
            data = f.read(256 * 1024)
            if not data:
                break
            sha1.update(data)
    return sha1.hexdigest()

def computeCacheKey(stage):
    if (stage['location'] == 'ThirdParty'):
        envKey = envForThirdPartyKey
    else:
        envKey = environmentKey
    objects = [
        envKey,
        stage['location'],
        stage['name'],
        stage['version'],
        stage['commands']
    ]
    for pattern in stage['dependencies']:
        pathlist = glob.glob(os.path.join(libsDir, pattern))
        items = [pattern]
        if len(pathlist) == 0:
            pathlist = glob.glob(os.path.join(thirdPartyDir, pattern))
        if len(pathlist) == 0:
            error('Nothing found: ' + pattern)
        for path in pathlist:
            if not os.path.exists(path):
                error('Not found: ' + path)
            items.append(computeFileHash(path))
        objects.append(':'.join(items))
    return hashlib.sha1(';'.join(objects).encode('utf-8')).hexdigest()

def keyPath(stage):
    return os.path.join(stage['directory'], keysLoc, stage['name'])

def checkCacheKey(stage):
    if not 'key' in stage:
        error('Key not set in stage: ' + stage['name'])
    key = keyPath(stage)
    if not os.path.exists(os.path.join(stage['directory'], stage['name'])):
        return 'NotFound'
    if not os.path.exists(key):
        return 'Stale'
    with open(key, 'r') as file:
        return 'Good' if (file.read() == stage['key']) else 'Stale'

def clearCacheKey(stage):
    key = keyPath(stage)
    if os.path.exists(key):
        os.remove(key)

def writeCacheKey(stage):
    if not 'key' in stage:
        error('Key not set in stage: ' + stage['name'])
    key = keyPath(stage)
    with open(key, 'w') as file:
        file.write(stage['key'])

stages = []

def removeDir(folder):
    if win:
        return 'if exist ' + folder + ' rmdir /Q /S ' + folder + '\nif exist ' + folder + ' exit /b 1'
    return 'rm -rf ' + folder

def setVar(key, multilineValue):
    singlelineValue = ' '.join(multilineValue.replace('\n', '').split());
    if win:
        return 'SET "' + key + '=' + singlelineValue + '"';
    return key + '="' + singlelineValue + '"';

def filterByPlatform(commands):
    commands = commands.split('\n')
    result = ''
    dependencies = []
    version = '0'
    skip = False
    for command in commands:
        m = re.match(r'(!?)([a-z0-9_]+):', command)
        if m and m.group(2) != 'depends' and m.group(2) != 'version':
            scopes = m.group(2).split('_')
            inscope = 'common' in scopes
            if win and 'win' in scopes:
                inscope = True
            if win32 and 'win32' in scopes:
                inscope = True
            if win64 and 'win64' in scopes:
                inscope = True
            if winarm and 'winarm' in scopes:
                inscope = True
            if mac and 'mac' in scopes:
                inscope = True
            if 'release' in scopes:
                if 'skip-release' in options:
                    inscope = False
                elif len(scopes) == 1:
                    continue
            skip = inscope if m.group(1) == '!' else not inscope
        elif not skip and not re.match(r'\s*#', command):
            if m and m.group(2) == 'version':
                version = version + '.' + command[len(m.group(0)):].strip()
            elif m and m.group(2) == 'depends':
                pattern = command[len(m.group(0)):].strip()
                dependencies.append(pattern)
            else:
                command = command.strip()
                if len(command) > 0:
                    result = result + command + '\n'
    return [result, dependencies, version]

def stage(name, commands, location = 'Libraries'):
    if location == 'Libraries':
        directory = libsDir
    elif location == 'ThirdParty':
        directory = thirdPartyDir
    else:
        error('Unknown location: ' + location)
    [commands, dependencies, version] = filterByPlatform(commands)
    if len(commands) > 0:
        stages.append({
            'name': name,
            'location': location,
            'directory': directory,
            'commands': commands,
            'version': version,
            'dependencies': dependencies
        })

def winFailOnEach(command):
    commands = command.split('\n')
    result = ''
    startingCommand = True
    for command in commands:
        command = re.sub(r'\$([A-Za-z0-9_]+)', r'%\1%', command)
        if re.search(r'\$[^<]', command):
            error('Bad command: ' + command)
        appendCall = startingCommand and not re.match(r'(if|for) ', command)
        called = 'call ' + command if appendCall else command
        result = result + called
        if command.endswith('^'):
            startingCommand = False
        else:
            startingCommand = True
            result = result + '\r\nif %errorlevel% neq 0 exit /b %errorlevel%\r\n'
    return result

def printCommands(commands):
    print('---------------------------------COMMANDS-LIST----------------------------------')
    print(commands, end='')
    print('--------------------------------------------------------------------------------')

def run(commands):
    printCommands(commands)
    if win:
        if os.path.exists("command.bat"):
            os.remove("command.bat")
        with open("command.bat", 'w') as file:
            file.write('@echo OFF\r\nset "NoDefaultCurrentDirectoryInExePath="\r\n' + winFailOnEach(commands))
        batPath = os.path.abspath("command.bat")
        result = subprocess.run(batPath, shell=True, env=modifiedEnv).returncode == 0
        if result and os.path.exists("command.bat"):
            os.remove("command.bat")
        return result
    elif re.search(r'\%', commands):
        error('Bad command: ' + commands)
    else:
        return subprocess.run("set -e\n" + commands, shell=True, env=modifiedEnv).returncode == 0

class _Getch:
    def __init__(self):
        try:
            self.impl = _GetchWindows()
        except ImportError:
            self.impl = _GetchUnix()
    def __call__(self): return self.impl()

class _GetchUnix:
    def __init__(self):
        import tty, sys
    def __call__(self):
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

class _GetchWindows:
    def __init__(self):
        import msvcrt
    def __call__(self):
        import msvcrt
        return msvcrt.getch().decode('ascii')

getch = _Getch()

def runStages():
    onlyStages = []
    rebuildStale = False
    for arg in sys.argv[1:]:
        if arg in options:
            continue
        elif arg == 'silent':
            rebuildStale = True
            continue
        found = False
        for stage in stages:
            if stage['name'] == arg:
                onlyStages.append(arg)
                found = True
                break
        if not found:
            error('Unknown argument: ' + arg)
    count = len(stages)
    index = 0
    for stage in stages:
        if len(onlyStages) > 0 and not stage['name'] in onlyStages:
            continue
        index = index + 1
        version = ('#' + str(stage['version'])) if (stage['version'] != '0') else ''
        prefix = '[' + str(index) + '/' + str(count) + '](' + stage['location'] + '/' + stage['name'] + version + ')'
        print(prefix + ': ', end = '', flush=True)
        stage['key'] = computeCacheKey(stage)
        commands = removeDir(stage['name']) + '\n' + stage['commands']
        checkResult = 'Forced' if len(onlyStages) > 0 else checkCacheKey(stage)
        if checkResult == 'Good':
            print('SKIPPING')
            continue
        elif checkResult == 'NotFound':
            print('NOT FOUND, ', end='')
        elif checkResult == 'Stale' or checkResult == 'Forced':
            if checkResult == 'Stale':
                print('CHANGED, ', end='')
            if rebuildStale:
                checkResult = 'Rebuild'
            else:
                print('(r)ebuild, rebuild (a)ll, (s)kip, (p)rint, (q)uit?: ', end='', flush=True)
                while True:
                    ch = 'r' if rebuildStale else getch()
                    if ch == 'q':
                        finish(0)
                    elif ch == 'p':
                        printCommands(commands)
                        checkResult = 'Printed'
                        break
                    elif ch == 's':
                        checkResult = 'Skip'
                        break
                    elif ch == 'r':
                        checkResult = 'Rebuild'
                        break
                    elif ch == 'a':
                        checkResult = 'Rebuild'
                        rebuildStale = True
                        break
        if checkResult == 'Printed':
            continue
        if checkResult == 'Skip':
            print('SKIPPING')
            continue
        clearCacheKey(stage)
        print('BUILDING:')
        os.chdir(stage['directory'])
        if not run(commands):
            print(prefix + ': FAILED')
            finish(1)
        writeCacheKey(stage)

runStages()
