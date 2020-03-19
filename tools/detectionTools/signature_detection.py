import csv
import io
import pandas as pd
import InputLog
import dateutil.parser
import time
from pytz import timezone
import write_log
import mysql.connector
import re

class SignatureDetector:

    EVENT_LOGIN="4624"
    EVENT_LOGIN_FAIL = "4625"
    EVENT_TGT = "4768"
    EVENT_ST="4769"
    EVENT_PRIV = "4672"
    EVENT_PROCESS = "4688"
    EVENT_PRIV_SERVICE = "4673"
    EVENT_PRIV_OPE = "4674"
    EVENT_NTLM = "4776"
    EVENT_SHARE = "5140"
    SYSTEM_DIR = "c:\windows";
    SYSTEM_DIR2 = "c:\program files";
    PSEXESVC = "psexesvc";
    ADMINSHARE="\c$"
    ADMINSHARE_2 = "admin$"
    IPC = "\ipc$"
    SYSTEM="system"
    ANONYMOUS="anonymous logon"
    CMD="cmd.exe"
    RUNDLL="rundll32.exe"
    RESULT_NORMAL="normal"
    RESULT_PRIV="attack: Unexpected privilege is used"
    RESULT_CMD="attack: command on blackList is used"
    RESULT_MAL_CMD = "attack: Abnormal command or tool is used"
    RESULT_ADMINSHARE = "attack: Admin share is used"
    RESULT_NOTGT="attack: Golden Ticket is used"
    RESULT_SID_MISMATCH = "attack: SID mismatch"
    RESULT_ROMANCE = "attack: Eternal Romance is used"
    RESULT_SILVER = "attack: Silver Ticket is used"
    WARN = "warning:ST without TGT"

    df=pd.DataFrame(data=None, index=None, columns=["datetime","eventid","accountname","clientaddr","servicename","processname","objectname","sharename", "securityid"], dtype=None, copy=False)
    df_admin = pd.DataFrame(data=None, index=None, columns=[ "accountname"], dtype=None, copy=False)
    df_cmd = pd.DataFrame(data=None, index=None, columns=["processname","tactics"], dtype=None, copy=False)
    df_cmd_white = pd.DataFrame(data=None, index=None, columns=["processname"], dtype=None, copy=False)

    cnt=0

    def __init__(self):
        print("constructor called")

    def is_attack(self):
        print("is_attack called")

    @staticmethod
    def signature_detect(datetime, eventid, accountname, clientaddr, servicename, processname, objectname, sharedname, securityid):
        """ Detect attack using signature based detection.
        :param datetime: Datetime of the event
        :param eventid: EventID
        :param accountname: Accountname
        :param clientaddr: Source IP address
        :param servicename: Service name
        :param processname: Process name(command name)
        :param objectname: Object name
        :return : True(1) if attack, False(0) if normal
        """

        inputLog = InputLog.InputLog(datetime, eventid, accountname, clientaddr, servicename, processname, objectname, sharedname, securityid)
        return SignatureDetector.signature_detect(inputLog)

    @staticmethod
    def signature_detect(inputLog):
        """ Detect attack using signature based detection.
        :param inputLog: InputLog object of the event
        :return : True(1) if attack, False(0) if normal
        """

        result=SignatureDetector.RESULT_NORMAL
        
        #write_log.Write_log(result, '', inputLog.get_datetime(), inputLog.get_clientaddr(), inputLog.get_eventid(), inputLog.get_accountname(), inputLog.get_clientaddr(), inputLog.get_servicename(), inputLog.get_processname(), inputLog.get_objectname(), inputLog.get_sharedname())


        if (inputLog.get_eventid()==SignatureDetector.EVENT_ST) :
            result=SignatureDetector.hasNoTGT(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_PRIV
              or inputLog.get_eventid() == SignatureDetector.EVENT_PRIV_SERVICE)\
                or inputLog.get_eventid() == SignatureDetector.EVENT_PRIV_OPE:
            result =SignatureDetector.isNotAdmin(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_PRIV_OPE
                or inputLog.get_eventid() == SignatureDetector.EVENT_PRIV_SERVICE):
            result = SignatureDetector.isSuspiciousProcess(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_PROCESS):
            result = SignatureDetector.isEternalBlue(inputLog)
            if (result== SignatureDetector.RESULT_NORMAL ):
                result = SignatureDetector.isSuspiciousProcess(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_SHARE):
            result = SignatureDetector.isEternalRomace(inputLog)
            if (result == SignatureDetector.RESULT_NORMAL):
                result = SignatureDetector.isEternalWin8(inputLog)
            if (result == SignatureDetector.RESULT_NORMAL):
                result = SignatureDetector.isEternalBlue(inputLog)
            if (result == SignatureDetector.RESULT_NORMAL):
                result =SignatureDetector.isAdminshare(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_LOGIN):
            result = SignatureDetector.compareSID(inputLog)
            if (result == SignatureDetector.RESULT_NORMAL):
                result = SignatureDetector.isEternalWin8(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_LOGIN_FAIL):
            result = SignatureDetector.compareSID(inputLog)

        elif (inputLog.get_eventid() == SignatureDetector.EVENT_NTLM):
            result = SignatureDetector.isEternalWin8(inputLog)

        series = pd.Series([inputLog.get_datetime(),inputLog.get_eventid(),inputLog.get_accountname(),inputLog.get_clientaddr(),
                      inputLog.get_servicename(),inputLog.get_processname(),inputLog.get_objectname(), inputLog.get_sharedname(), inputLog.get_securityid()], index=SignatureDetector.df.columns)
        SignatureDetector.df=SignatureDetector.df.append(series, ignore_index = True)

        return result

    @staticmethod
    def compareSID(inputLog):
        accountname=inputLog.get_accountname()
        sid=inputLog.get_securityid()

        # if sid is not domain SID, exclude from detection
        pattern = 's\-[0-9]+\-'
        result = re.match(pattern, sid)
        if result:
            sid_list = sid.split('-')
            if len(sid_list)<5:
                 return SignatureDetector.RESULT_NORMAL

        # if accounname or sid is not recorded, exclude from detection
        # if sid is system, exclude from detection
        if accountname == '-' or sid == 'NULL SID' or sid == 'system':
            return SignatureDetector.RESULT_NORMAL

        conn = mysql.connector.connect(user='root', host='localhost', password='Passw0rd!', database='account')
        cur = conn.cursor(buffered=True)
        try:
            # accountname does not match sid
            if accountname != sid:
                # compare accountname and sid using master DB
                query = "select sid from users where username=%s"
                cur.execute(query,(accountname, ))
                for row in cur.fetchall():
                    sid_db=str(row[0]).lower()
                    # accountname and sid exsist in master DB
                    if sid_db==sid:
                        return SignatureDetector.RESULT_NORMAL

                query2 = "select sid from users where sid=%s"
                cur.execute(query2, (sid,))
                # accountname does not exist but sid exsist in master DB
                if cur.rowcount>0:
                    print("Signature D: " + SignatureDetector.RESULT_SID_MISMATCH + "sid:" + sid + ", account:" + accountname)
                    return SignatureDetector.RESULT_SID_MISMATCH

                # accountname and sid does not exsist in master DB
                # check whether account has domain admin privilage
                logs = SignatureDetector.df_admin[
                    (SignatureDetector.df_admin.accountname == inputLog.get_accountname())]
                if len(logs) == 0:
                    # account does not have admin privilage
                    return SignatureDetector.RESULT_NORMAL

                print("Signature D: " + SignatureDetector.RESULT_SID_MISMATCH+"sid:"+sid+", account:"+accountname)
                return SignatureDetector.RESULT_SID_MISMATCH
            else:
                return SignatureDetector.RESULT_NORMAL
        finally:
            cur.close()
            conn.close()

    @staticmethod
    def hasNoTGT(inputLog):
        time.sleep(1)
        SignatureDetector.df["eventid"]=SignatureDetector.df["eventid"].astype(str)
        logs=SignatureDetector.df[(SignatureDetector.df.accountname == inputLog.get_accountname())
                                  &(SignatureDetector.df.clientaddr==inputLog.get_clientaddr())
                                  & (SignatureDetector.df.eventid == SignatureDetector.EVENT_TGT)
        ]
        if len(logs)==0:
            print("Signature D: " + SignatureDetector.WARN)
            return SignatureDetector.WARN
        else:
            return SignatureDetector.RESULT_NORMAL

    @staticmethod
    def isNotAdmin(inputLog):
        logs = SignatureDetector.df_admin[(SignatureDetector.df_admin.accountname == inputLog.get_accountname())]
        if len(logs) == 0:
            print("Signature A: " + SignatureDetector.RESULT_PRIV)
            return SignatureDetector.RESULT_PRIV
        else:
            return SignatureDetector.RESULT_NORMAL

    @staticmethod
    def isSuspiciousProcess(inputLog):

        logs = SignatureDetector.df[(SignatureDetector.df.accountname == inputLog.get_accountname())
                                    & (SignatureDetector.df.eventid == SignatureDetector.EVENT_ST)
                                    ]
        latestlog=logs.tail(1)
        if(len(latestlog)>0):
            clientaddr=latestlog.clientaddr.values[0]
            inputLog.set_clientaddr(clientaddr)

        #print(inputLog.get_clientaddr()+","+inputLog.get_accountname())

        if (inputLog.get_processname().find(SignatureDetector.SYSTEM_DIR)==-1 and inputLog.get_processname().find(SignatureDetector.SYSTEM_DIR2)==-1):
            #print("Signature B: "+SignatureDetector.RESULT_MAL_CMD)
            return SignatureDetector.RESULT_MAL_CMD
        cmds=inputLog.get_processname().split("\\")
        cmd=cmds[len(cmds)-1]
        logs = SignatureDetector.df_cmd[SignatureDetector.df_cmd.processname.str.contains(cmd)]
        if len(logs)>0:
            #print("Signature B: " + SignatureDetector.RESULT_CMD)
            return SignatureDetector.RESULT_CMD

        if (inputLog.get_objectname().find(SignatureDetector.PSEXESVC)>=0):
            #print("Signature B: " + SignatureDetector.RESULT_CMD)
            return SignatureDetector.RESULT_CMD

        return SignatureDetector.RESULT_NORMAL

    @staticmethod
    def check_cmd_whitelist(processname):
        logs = SignatureDetector.df_cmd_white[(SignatureDetector.df_cmd_white.processname == processname)]
        if len(logs) == 0:
            print("Signature B: " + SignatureDetector.RESULT_CMD)
            return SignatureDetector.RESULT_CMD
        else:
            return SignatureDetector.RESULT_NORMAL

    @staticmethod
    def isAdminshare(inputLog):
        if inputLog.get_sharedname().find(SignatureDetector.ADMINSHARE)>=0:
            print("Signature C: " + SignatureDetector.RESULT_ADMINSHARE)
            return SignatureDetector.RESULT_ADMINSHARE

        return SignatureDetector.RESULT_NORMAL


    @staticmethod
    def isEternalRomace(inputLog):
        time.sleep(1)
        logs = None
        # share name is 'IPC' and account is computer account
        if (inputLog.get_sharedname().find(SignatureDetector.IPC) >= 0 and inputLog.get_accountname().endswith("$")):
            # Check whether admin share with computer account is used within 2 seconds
            logs = SignatureDetector.df[SignatureDetector.df.accountname.str.endswith("$")]
            logs = logs[(SignatureDetector.df.clientaddr == inputLog.get_clientaddr())
                        & ((SignatureDetector.df.sharename.str.endswith(SignatureDetector.ADMINSHARE)
                            | SignatureDetector.df.sharename.str.endswith(SignatureDetector.ADMINSHARE_2)))]

        if (inputLog.get_sharedname().find(SignatureDetector.ADMINSHARE) >= 0 or inputLog.get_sharedname().find(
                SignatureDetector.ADMINSHARE_2) >= 0):
            # account name ends with '$'
            if (inputLog.get_accountname().endswith("$")):
                logs = SignatureDetector.df[SignatureDetector.df.accountname.str.endswith("$")]
                logs = logs[(SignatureDetector.df.clientaddr == inputLog.get_clientaddr())
                            & (SignatureDetector.df.sharename.str.endswith(SignatureDetector.IPC))]

        if ((logs is not None) and len(logs) > 0):
            now = dateutil.parser.parse(inputLog.get_datetime())
            last_date=now
            try:
                now = timezone('UTC').localize(now)
                last_date = dateutil.parser.parse(logs.tail(1).datetime.str.cat())
                last_date = timezone('UTC').localize(last_date)
            except:
                print("")
            diff = (last_date - now).total_seconds()
            if (diff < 2):
                print("Signature E(EternalRomace): " + SignatureDetector.RESULT_ROMANCE)
                return SignatureDetector.RESULT_ROMANCE

        return SignatureDetector.RESULT_NORMAL


    @staticmethod
    def isEternalWin8(inputLog):
        time.sleep(1)
        logs = None
        logs_login = None
        logs_ntlm = None
        logs_share = None

        # share name is 'IPC'
        if (inputLog.get_sharedname().find(SignatureDetector.IPC) >= 0):
            # Check whether 4624 and 4776 events are recorded from the same account within 2 seconds
            logs = SignatureDetector.df[SignatureDetector.df.accountname == inputLog.get_accountname()]
            if ((logs is not None) and len(logs) > 0):
                logs_login = logs[(SignatureDetector.df.eventid == SignatureDetector.EVENT_LOGIN) &
                                  (SignatureDetector.df.clientaddr == inputLog.get_clientaddr())]
                logs_ntlm = logs[(SignatureDetector.df.eventid == SignatureDetector.EVENT_NTLM)]

            if ((logs_login is not None) and len(logs_login) > 0) and ((logs_ntlm is not None) and (len(logs_ntlm) > 0)):
                now = dateutil.parser.parse(inputLog.get_datetime())
                last_date=now
                try:
                    now = timezone('UTC').localize(now)
                    last_date = dateutil.parser.parse(logs_login.tail(1).datetime.str.cat())
                    last_date = timezone('UTC').localize(last_date)
                    diff_login = (last_date - now).total_seconds()

                    last_date = dateutil.parser.parse(logs_ntlm.tail(1).datetime.str.cat())
                    last_date = timezone('UTC').localize(last_date)
                except:
                    print("")
                diff_ntlm = (last_date - now).total_seconds()

                if (diff_login < 2 and diff_ntlm < 2):
                    SignatureDetector.cnt = SignatureDetector.cnt + 1
                    if SignatureDetector.cnt >= 2:
                        print("Signature E(EternalWin8): " + SignatureDetector.RESULT_ROMANCE)
                        return SignatureDetector.RESULT_ROMANCE

        # 4624
        if (inputLog.get_eventid() == SignatureDetector.EVENT_LOGIN):
            # Check whether 5140 and 4776 events are recorded from the same account within 2 seconds
            logs = SignatureDetector.df[SignatureDetector.df.accountname == inputLog.get_accountname()]
            if ((logs is not None) and len(logs) > 0):
                logs_share = logs[(SignatureDetector.df.eventid == SignatureDetector.EVENT_SHARE) &
                                  (SignatureDetector.df.clientaddr == inputLog.get_clientaddr()) &
                                  (SignatureDetector.df.sharename.str.endswith(SignatureDetector.IPC))
                                  ]
                logs_ntlm = logs[(SignatureDetector.df.eventid == SignatureDetector.EVENT_NTLM)]

            if ((logs_share is not None) and len(logs_share) > 0) and ((logs_ntlm is not None) and (len(logs_ntlm) > 0)):
                now = dateutil.parser.parse(inputLog.get_datetime())
                last_date=now
                try:
                    now = timezone('UTC').localize(now)
                    last_date = dateutil.parser.parse(logs_share.tail(1).datetime.str.cat())
                    last_date = timezone('UTC').localize(last_date)
                    diff_share = (last_date - now).total_seconds()

                    last_date = dateutil.parser.parse(logs_ntlm.tail(1).datetime.str.cat())
                    last_date = timezone('UTC').localize(last_date)
                except:
                    print('')
                diff_ntlm = (last_date - now).total_seconds()

                if (diff_share < 2 and diff_ntlm < 2):
                    SignatureDetector.cnt = SignatureDetector.cnt + 1
                    if SignatureDetector.cnt >= 2:
                        print("Signature E(EternalWin8): " + SignatureDetector.RESULT_ROMANCE)
                        return SignatureDetector.RESULT_ROMANCE

        # 4776
        if (inputLog.get_eventid() == SignatureDetector.EVENT_NTLM):
            # Check whether 5140 and 4624 events are recorded from the same account within 2 seconds
            logs = SignatureDetector.df[SignatureDetector.df.accountname == inputLog.get_accountname()]
            if ((logs is not None) and len(logs) > 0):
                logs_share = logs[(SignatureDetector.df.eventid == SignatureDetector.EVENT_SHARE) &
                                  (SignatureDetector.df.sharename.str.endswith(SignatureDetector.IPC))
                                  ]
                logs_login = logs[(SignatureDetector.df.eventid == SignatureDetector.EVENT_LOGIN)]

            if ((logs_share is not None) and len(logs_share) > 0) and ((logs_login is not None) and (len(logs_login) > 0)):
                now = dateutil.parser.parse(inputLog.get_datetime())
                last_date=now
                try:
                    now = timezone('UTC').localize(now)
                    last_date = dateutil.parser.parse(logs_share.tail(1).datetime.str.cat())
                    last_date = timezone('UTC').localize(last_date)
                    diff_share = (last_date - now).total_seconds()

                    last_date = dateutil.parser.parse(logs_login.tail(1).datetime.str.cat())
                    last_date = timezone('UTC').localize(last_date)
                except:
                    print()
                diff_login = (last_date - now).total_seconds()

                if (diff_share < 2 and diff_login < 2):
                    SignatureDetector.cnt = SignatureDetector.cnt + 1
                    if SignatureDetector.cnt >= 2:
                        print("Signature E(EternalWin8): " + SignatureDetector.RESULT_ROMANCE)
                        return SignatureDetector.RESULT_ROMANCE

        return SignatureDetector.RESULT_NORMAL


    @staticmethod
    def isEternalBlue(inputLog):
        time.sleep(1)
        logs = None

        # security id is system and (process name is cmd.exe or rundll32.exe)
        if (inputLog.get_securityid() == SignatureDetector.SYSTEM and
                (inputLog.get_processname().endswith(SignatureDetector.CMD)
                 or inputLog.get_processname().endswith(SignatureDetector.RUNDLL))
        ):
            # Check whether ANONYMOUS IPC access is used within 2 seconds
            logs = SignatureDetector.df[((SignatureDetector.df.securityid == SignatureDetector.ANONYMOUS) | (
                        SignatureDetector.df.accountname == SignatureDetector.ANONYMOUS))
                                        & (SignatureDetector.df.sharename.str.endswith(SignatureDetector.IPC))]

        # security id is ANONYMOUS and share name is IPC security id is system and (process name is cmd.exe or rundll32) is recorded  within 2 seconds
        if ((
                inputLog.get_securityid() == SignatureDetector.ANONYMOUS or inputLog.get_accountname() == SignatureDetector.ANONYMOUS)
                and inputLog.get_sharedname().endswith(SignatureDetector.IPC)):
            # Check whether
            logs = SignatureDetector.df[(SignatureDetector.df.securityid == SignatureDetector.SYSTEM)
                                        & (
                                            ((SignatureDetector.df.processname.str.endswith(SignatureDetector.CMD) |
                                              (SignatureDetector.df.processname.str.endswith(SignatureDetector.RUNDLL))
                                              ))
                                        )]
        # Check whether admin share is used
        if (inputLog.get_eventid() == SignatureDetector.EVENT_SHARE and SignatureDetector.isAdminshare(
                inputLog) == SignatureDetector.RESULT_ADMINSHARE):
            logs = SignatureDetector.df[(SignatureDetector.df.securityid == SignatureDetector.SYSTEM)
                                        & (
                                            ((SignatureDetector.df.processname.str.endswith(SignatureDetector.CMD) |
                                              (SignatureDetector.df.processname.str.endswith(SignatureDetector.RUNDLL))
                                              ))
                                        )]

        if ((logs is not None) and len(logs) > 0):
            now = dateutil.parser.parse(inputLog.get_datetime())
            last_date =now
            try:
                now = timezone('UTC').localize(now)
                last_date = dateutil.parser.parse(logs.tail(1).datetime.str.cat())
                last_date = timezone('UTC').localize(last_date)
            except:
                print()
            diff = (last_date - now).total_seconds()
            if (diff <= 10):
                print("Signature E(EternalBlue): " + SignatureDetector.RESULT_ROMANCE)
                return SignatureDetector.RESULT_ROMANCE

        return SignatureDetector.RESULT_NORMAL
