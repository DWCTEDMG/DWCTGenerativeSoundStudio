import React, { useState } from 'react';
import { ActivityIndicator, Alert, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { StatusBar } from 'expo-status-bar';

export default function App() {
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState('Not connected');

  async function checkConnection() {
    const base = url.trim().replace(/\/+$/, '');
    if (!/^https:\/\//i.test(base)) {
      Alert.alert('HTTPS required', 'Enter your secure backend HTTPS URL. Do not expose port 7863 directly to the internet.');
      return;
    }
    setChecking(true);
    try {
      const saved = await SecureStore.getItemAsync('backend_token');
      const auth = token.trim() || saved || '';
      if (token.trim()) await SecureStore.setItemAsync('backend_token', token.trim());
      const response = await fetch(base + '/health/', {
        headers: auth ? { Authorization: 'Bearer ' + auth } : {},
      });
      const payload = await response.json();
      setResult(response.ok ? 'Backend reachable: ' + JSON.stringify(payload) : 'HTTP ' + response.status);
    } catch (error) {
      setResult('Connection failed: ' + (error instanceof Error ? error.message : String(error)));
    } finally {
      setChecking(false);
    }
  }

  return (
    <SafeAreaView style={styles.page}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.eyebrow}>DWCT PRODUCTIONS</Text>
        <Text style={styles.title}>Studio Mobile</Text>
        <Text style={styles.subtitle}>Your music-to-video workspace, powered by your remote FastAPI and NVIDIA backend.</Text>
        <View style={styles.panel}>
          <Text style={styles.heading}>Backend connection</Text>
          <Text style={styles.label}>HTTPS backend URL</Text>
          <TextInput style={styles.input} placeholder="https://studio-api.example.com" placeholderTextColor="#8790a3" autoCapitalize="none" autoCorrect={false} keyboardType="url" value={url} onChangeText={setUrl} />
          <Text style={styles.label}>Access token (optional for health checks)</Text>
          <TextInput style={styles.input} placeholder="Bearer token" placeholderTextColor="#8790a3" secureTextEntry autoCapitalize="none" value={token} onChangeText={setToken} />
          <TouchableOpacity style={styles.button} onPress={checkConnection} disabled={checking}>
            {checking ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Test connection</Text>}
          </TouchableOpacity>
          <Text selectable style={styles.result}>{result}</Text>
        </View>
        <View style={styles.panel}>
          <Text style={styles.heading}>Coming next</Text>
          <Text style={styles.subtitle}>Audio upload · Projects · Storyboards · Render queue · Video previews</Text>
          <Text style={styles.note}>Generation controls will be connected only after confirming the backend's authenticated API contracts.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: '#090d19' },
  content: { padding: 24, gap: 18 },
  eyebrow: { color: '#67e8f9', fontSize: 12, letterSpacing: 3, fontWeight: '700', marginTop: 16 },
  title: { color: '#fff', fontSize: 36, fontWeight: '800' },
  subtitle: { color: '#a9b4c8', fontSize: 15, lineHeight: 23 },
  panel: { backgroundColor: '#161d31', borderRadius: 20, padding: 20, gap: 12, borderColor: '#28324b', borderWidth: 1 },
  heading: { color: '#fff', fontSize: 20, fontWeight: '700' },
  label: { color: '#cbd5e1', fontSize: 13 },
  input: { backgroundColor: '#0d1425', borderRadius: 12, borderColor: '#39445d', borderWidth: 1, padding: 14, color: '#fff', fontSize: 15 },
  button: { backgroundColor: '#635bff', borderRadius: 12, padding: 16, alignItems: 'center' },
  buttonText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  result: { color: '#67e8f9', lineHeight: 20 },
  note: { color: '#8790a3', fontSize: 12, lineHeight: 18 },
});
