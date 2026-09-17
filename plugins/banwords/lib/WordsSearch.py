#!/usr/bin/env python
# -*- coding:utf-8 -*-
# ToolGood.Words.WordsSearch.py
# 2020, Lin Zhijun, https://github.com/toolgood/ToolGood.Words
# Licensed under the Apache License 2.0
# 更新日志
# 2020.04.06 第一次提交
# 2020.05.16 修改，支持大于0xffff的字符

__all__ = ['WordsSearch']
__author__ = 'Lin Zhijun'
__date__ = '2020.05.16'

class TrieNode():
    def __init__(self):
        self.Index = 0
        self.Index = 0
        self.Layer = 0
        self.End = False
        self.Char = ''
        self.Results = []
        self.m_values = {}
        self.Failure = None
        self.Parent = None

    def Add(self,c):
        if c in self.m_values :
            return self.m_values[c]
        node = TrieNode()
        node.Parent = self
        node.Char = c
        self.m_values[c] = node
        return node

    def SetResults(self,index):
        if (not self.End):
            self.End = True
        self.Results.append(index)

class TrieNode2():
    def __init__(self):
        self.End = False
        self.Results = []
        self.m_values = {}
        self.minflag = 0xffff
        self.maxflag = 0

    def Add(self,c,node3):
        if (self.minflag > c):
            self.minflag = c
        if (self.maxflag < c):
             self.maxflag = c
        self.m_values[c] = node3

    def SetResults(self,index):
        if (not self.End) :
            self.End = True
        if index not in self.Results :
            self.Results.append(index)

    def HasKey(self,c):
        return c in self.m_values


    def TryGetValue(self,c):
        if (self.minflag <= c and self.maxflag >= c):
            if c in self.m_values:
                return self.m_values[c]
        return None


class WordsSearch():
    def __init__(self):
        self._first = {}
        self._keywords = []
        self._indexs=[]

    def SetKeywords(self,keywords):
        self._keywords = keywords
        self._indexs=[]
        for i in range(len(keywords)):
            self._indexs.append(i)

        root = TrieNode()
        allNodeLayer={}

        for i in range(len(self._keywords)): # for (i = 0; i < _keywords.length; i++)
            p = self._keywords[i]
            nd = root
            for j in range(len(p)): # for (j = 0; j < p.length; j++)
                nd = nd.Add(ord(p[j]))
                if (nd.Layer == 0):
                    nd.Layer = j + 1
                    if nd.Layer in allNodeLayer:
                        allNodeLayer[nd.Layer].append(nd)
                    else:
                        allNodeLayer[nd.Layer]=[]
                        allNodeLayer[nd.Layer].append(nd)
            nd.SetResults(i)


        allNode = []
        allNode.append(root)
        for key in allNodeLayer.keys():
            for nd in allNodeLayer[key]:
                allNode.append(nd)
        allNodeLayer=None

        for i in range(len(allNode)): # for (i = 0; i < allNode.length; i++)
            if i==0 :
                continue
            nd=allNode[i]
            nd.Index = i
            r = nd.Parent.Failure
            c = nd.Char
            while (r is not None and c not in r.m_values):
                r = r.Failure
            if (r is None):
                nd.Failure = root
            else:
                nd.Failure = r.m_values[c]
                for key2 in nd.Failure.Results :
                    nd.SetResults(key2)
        root.Failure = root

        allNode2 = []
        for i in range(len(allNode)): # for (i = 0; i < allNode.length; i++)
            allNode2.append( TrieNode2())

        for i in range(len(allNode2)): # for (i = 0; i < allNode2.length; i++)
            oldNode = allNode[i]
            newNode = allNode2[i]

            for key in oldNode.m_values :
                index = oldNode.m_values[key].Index
                newNode.Add(key, allNode2[index])

            for index in range(len(oldNode.Results)): # for (index = 0; index < oldNode.Results.length; index++)
                item = oldNode.Results[index]
                newNode.SetResults(item)

            oldNode=oldNode.Failure
            while oldNode != root:
                for key in oldNode.m_values :
                    if (not newNode.HasKey(key)):
                        index = oldNode.m_values[key].Index
                        newNode.Add(key, allNode2[index])
                for index in range(len(oldNode.Results)):
                    item = oldNode.Results[index]
                    newNode.SetResults(item)
                oldNode=oldNode.Failure
        allNode = None
        root = None

        # first = []
        # for index in range(65535):# for (index = 0; index < 0xffff; index++)
        #     first.append(None)

        # for key in allNode2[0].m_values :
        #     first[key] = allNode2[0].m_values[key]

        self._first = allNode2[0]


    def FindFirst(self,text):
        ptr = None
        for index in range(len(text)): # for (index = 0; index < text.length; index++)
            t =ord(text[index]) # text.charCodeAt(index)
            tn = None
            if (ptr is None):
                tn = self._first.TryGetValue(t)
            else:
                tn = ptr.TryGetValue(t)
                if (tn is None):
                    tn = self._first.TryGetValue(t)


            if (tn is not None):
                if (tn.End):
                    item = tn.Results[0]
                    keyword = self._keywords[item]
                    return { "Keyword": keyword, "Success": True, "End": index, "Start": index + 1 - len(keyword), "Index": self._indexs[item] }
            ptr = tn
        return None

    def FindAll(self,text):
        ptr = None
        list = []

        for index in range(len(text)): # for (index = 0; index < text.length; index++)
            t =ord(text[index]) # text.charCodeAt(index)
            tn = None
            if (ptr is None):
                tn = self._first.TryGetValue(t)
            else:
                tn = ptr.TryGetValue(t)
                if (tn is None):
                    tn = self._first.TryGetValue(t)


            if (tn is not None):
                if (tn.End):
                    for j in range(len(tn.Results)): # for (j = 0; j < tn.Results.length; j++)
                        item = tn.Results[j]
                        keyword = self._keywords[item]
                        list.append({ "Keyword": keyword, "Success": True, "End": index, "Start": index + 1 - len(keyword), "Index": self._indexs[item] })
            ptr = tn
        return list


    def ContainsAny(self,text):
        ptr = None
        for index in range(len(text)): # for (index = 0; index < text.length; index++)
            t =ord(text[index]) # text.charCodeAt(index)
            tn = None
            if (ptr is None):
                tn = self._first.TryGetValue(t)
            else:
                tn = ptr.TryGetValue(t)
                if (tn is None):
                    tn = self._first.TryGetValue(t)

            if (tn is not None):
                if (tn.End):
                    return True
            ptr = tn
        return False

    def Replace(self,text, replaceChar = '*'):
        result = list(text)

        ptr = None
        for i in range(len(text)): # for (i = 0; i < text.length; i++)
            t =ord(text[i]) # text.charCodeAt(index)
            tn = None
            if (ptr is None):
                tn = self._first.TryGetValue(t)
            else:
                tn = ptr.TryGetValue(t)
                if (tn is None):
                    tn = self._first.TryGetValue(t)

            if (tn is not None):
                if (tn.End):
                    maxLength = len( self._keywords[tn.Results[0]])
                    start = i + 1 - maxLength
                    for j in range(start,i+1): # for (j = start; j <= i; j++)
                        result[j] = replaceChar
            ptr = tn
        return ''.join(result)
