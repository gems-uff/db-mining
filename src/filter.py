#!/usr/bin/env python
# coding: utf-8

# In[1]:


import pandas as pd
import numpy as np
import matplotlib.pyplot as plt 


# In[2]:


from util import PROJECTS_FILE, FILTERED_FILE
#reads projects from Excel file
df = pd.read_excel(PROJECTS_FILE, keep_default_na=False)
len(df)


# In[3]:


df=df[df.stargazers >= 5000]
len(df)


# In[4]:


df = df[df.contributors >= 10]
df = df[df.commits >= 5000]
len(df)


# In[5]:


df = df[df.languages > 0]
len(df)


# In[6]:


df.primaryLanguage.value_counts()


# In[7]:


len(df.primaryLanguage.value_counts())


# In[8]:


#filters repositories by language, keeping just the ones that use the top 10 languages in the corpus 
df = df.groupby('primaryLanguage').filter(lambda x: len(x) >= 18)
len(df)


# In[9]:


pd.set_option('display.max_colwidth', -1) 
df


# In[10]:


df.describe()


# In[11]:


#saves filtered projetcts to Excel
#removes timezone from dates, since Excel does not know how to handle that
df.createdAt = pd.to_datetime(df.createdAt).dt.tz_localize(None) 
df.pushedAt = pd.to_datetime(df.pushedAt).dt.tz_localize(None)
df.to_excel(FILTERED_FILE, index=False)


# In[12]:


df.primaryLanguage.value_counts().plot(kind='pie', autopct='%1.1f%%')


# In[13]:


hist = df.hist(column=['stargazers'], bins=50)


# In[14]:


hist = df.hist(column=['languages'], bins=50)


# In[15]:


hist = df.hist(column=['contributors'], bins=100)


# In[16]:


hist = df.hist(column=['issues'], bins=100)


# In[17]:


hist = df.hist(column=['commits'], bins=100)


# In[18]:


hist = df.hist(column=['branches'], bins=100)


# In[19]:


hist = df.hist(column=['diskUsage'], bins=100)
plt.xlabel("KB")


# In[20]:


corr = df.drop('isMirror', axis=1).corr()
corr.style.background_gradient(cmap='Reds')


# In[ ]:




