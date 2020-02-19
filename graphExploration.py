from functions import getPlayersPastPVE, getPGCR, getJSONfromURL
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import BUNGIE_RR_TOKEN
import pandas as pd
import requests
import json
import matplotlib.pyplot as plt
from decimal import Decimal
import os
import queue
import random
plt.rcParams['backend'] = "Qt4Agg"

bungieAPI_URL = "https://www.bungie.net/Platform"
PARAMS = {'x-api-key': BUNGIE_RR_TOKEN}
dummy = None
session = requests.Session()
q = queue.Queue()

q.put(4611686018476935749) 

edges = pd.DataFrame(columns=['from', 'to', 'weight'])
vertices = pd.DataFrame(columns=['id', 'name'])
if os.path.exists('raiddata/edges.pickle'):
    edges = pd.read_pickle("raiddata/edges.pickle")
if os.path.exists('raiddata/vertices.pickle'):
    vertices = pd.read_pickle("raiddata/vertices.pickle")

if not os.path.lexists('raiddata'):
    os.mkdir('raiddata')
if not os.path.exists('raiddata/friendpickle'):
    os.mkdir('raiddata/friendpickle')

# missinglist = [e for e in edges['to'] if e not in vertices['id']] + [e for e in edges['from'] if e not in vertices['id']]
# map(q.put, missinglist)
# random nodes that didn't get indexed yet

while not q.empty():
    centerNodeDestinyID = q.get()
    #loop while users already exist, find new one
    while os.path.exists(f'raiddata/friendpickle/{centerNodeDestinyID}.pickle'):
        #add friends of existing member #BF
        for friend in pd.read_pickle(f"raiddata/friendpickle/{centerNodeDestinyID}.pickle")['to']:
            #if friend isn't in the link-list yet
            if not os.path.exists(f'raiddata/friendpickle/{friend}.pickle'):
                #queue up for analysis
                q.put(friend)
                #print('added ', friend, ' to the queue')
            else:
                if q.empty() or q.qsize()<3:
                    q.put(friend)
                    #print('added ', friend, ' to the queue')

                #fill in lost names
                if str(friend) not in vertices['id'].values:
                    for platform in [3,2,1,4,5,10,254]:
                        profileURL = "https://stats.bungie.net/Platform/Destiny2/{}/Profile/{}/?components=100,200"
                        characterinfo = session.get(url=profileURL.format(platform,friend), headers=PARAMS).json()
                        if not 'Response' in characterinfo:
                            continue
                        response = characterinfo['Response']
                        name = response['profile']['data']['userInfo']['displayName']
                        vertices = vertices.append({'id': str(friend),'name': name}, ignore_index= True)
                        vertices.to_pickle("raiddata/vertices.pickle")
                        print(f'added {name}:{friend} to vertices.pickle')
                        break

        centerNodeDestinyID = q.get()
        #pull next from queue to analyse
    for platform in [3,2,1,4,5,10,254]:
        charURL = "https://stats.bungie.net/Platform/Destiny2/{}/Profile/{}/?components=100,200"
        characterinfo = session.get(url=charURL.format(platform,centerNodeDestinyID), headers=PARAMS).json()
        if 'Response' in characterinfo.keys():
            break
    if not characterinfo:
        print('nothing found for ', centerNodeDestinyID)
        continue
    charIDs = characterinfo['Response']['characters']['data'].keys()
    activitylist = []
    isPrivate = False
    for characterID in charIDs:
        for pagenr in range(100):
            staturl = f"https://www.bungie.net/Platform/Destiny2/{platform}/Account/{centerNodeDestinyID}/Character/{characterID}/Stats/Activities/?mode=4&count=250&page={pagenr}" 
            # None	    0 Everything
            # Story	    2	 
            # Strike	3	 
            # Raid  	4	 
            # AllPvP	5	 
            # Patrol	6	 
            # AllPvE	7	
            rep = session.get(url=staturl, headers=PARAMS).json()
            if not rep or not 'Response' in rep or not rep['Response'] or 'activities' not in rep['Response']:
                if rep['ErrorCode'] == 1665:
                    isPrivate = True
                #no more data found for the character, moving on to next
                break
            activitylist += rep['Response']['activities']
    if isPrivate:
        continue
    #save for safety
    # with open(f'raiddata/{centerNodeDestinyID}.activitylist', 'w+') as f:
    #     f.write(json.dumps(activitylist))

    #only account for completed activities
    completedacts = []
    for act in activitylist:
        if act['values']['completed']['basic']['value'] == 1:
            completedacts.append(act)

    #get all ids needed for the pgcr reports
    instanceIds = [act['activityDetails']['instanceId'] for act in completedacts]
    print(f'found {len(instanceIds)} instances for user {centerNodeDestinyID}')
    
    if not instanceIds:
        continue

    #aquire all the pgcr data
    pgcrlist = []
    for instanceId in instanceIds:
        pgcrurl = f'https://stats.bungie.net/Platform/Destiny2/Stats/PostGameCarnageReport/{instanceId}/'
        response = session.get(url=pgcrurl, headers=PARAMS).json()['Response']
        if not response:
            print(f'===================================\nCRITICAL ERROR ON {centerNodeDestinyID}\n===================================')
            break
        pgcrlist += response['entries']
    # with open(f'raiddata/pgcr/{centerNodeDestinyID}.pgcr', 'w+') as f:
    #     f.write(json.dumps(pgcrlist))

    #extract partners from pgcrlist
    partners = []
    

    for char in pgcrlist:
        user = char['player']['destinyUserInfo']
        if 'displayName' not in char['player']['destinyUserInfo'].keys():
            continue
        partners.append((user['membershipId'], user['displayName']))

    #put them into a dataframe, group by unique users and count the common raids
    df = pd.DataFrame(partners, columns=['destinyid','username'])

    #get people and names from df
    vx = df.drop_duplicates(subset='destinyid')
    vx_nicely_named = vx.rename(columns = {'destinyid':'id', 'username':'name'})
    vertices = vertices.append(vx_nicely_named).drop_duplicates(subset='id')
    vertices.to_pickle(f'raiddata/vertices.pickle')

    #get edges and weights
    count = df.groupby(['destinyid','username']).size().reset_index(name='counts')
    sortedcount = count.sort_values('counts', ascending=False)
    sortedcount.drop(sortedcount.index[0], inplace=True)

    sortedcount['from'] = [centerNodeDestinyID]*len(sortedcount.index)

    outputedge = pd.DataFrame(columns=['from', 'to', 'weight'])
    outputedge['from'] = sortedcount['from']
    outputedge['to'] = sortedcount['destinyid']
    outputedge['weight'] = sortedcount['counts']
    outputedge.to_pickle(f'raiddata/friendpickle/{centerNodeDestinyID}.pickle')


    edges = edges.append(outputedge, sort = False)
    edges.drop_duplicates(subset=['from', 'to'], inplace=True)
    #edges = edges[edges['from'] > edges['to']]
    edges.to_pickle(f'raiddata/edges.pickle')


    print(f'done with {centerNodeDestinyID}')
    for did in outputedge['to'].values:
        q.put(did)


# smallsample = sortedcount.drop(sortedcount.index[0]).nlargest(20,'counts')
# smallsample.plot(x='username', y='counts', kind='bar')
# plt.gcf().subplots_adjust(bottom=0.4)
# plt.savefig('img.png')
# print('done')

