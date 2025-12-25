# eBay Agent Cockpit Mobile App

React Native mobile application for eBay Agent Cockpit with Expo.

## Features

- **Alert Management**: Create, manage, and monitor price alerts
- **Price Forecasting**: ML-powered price predictions
- **Trend Analysis**: Market trend insights and analysis
- **Push Notifications**: Real-time alerts on iOS and Android
- **Analytics Dashboard**: Track savings and market trends
- **SMS Notifications**: Integration with SMS service
- **User Profiles**: Account management and settings

## Setup

### Prerequisites

- Node.js 16+
- npm or yarn
- Expo CLI

### Installation

```bash
cd mobile-app
npm install
```

### Running the App

```bash
# Start development server
npm start

# Run on iOS simulator
npm run ios

# Run on Android emulator
npm run android

# Run on web
npm run web
```

## Project Structure

```
mobile-app/
├── screens/              # Screen components
│   ├── HomeScreen.tsx
│   ├── ProfileScreen.tsx
│   ├── AnalyticsScreen.tsx
│   └── ...
├── store/               # State management (Zustand)
│   ├── auth.ts
│   └── ...
├── components/          # Reusable components
├── services/           # API services
├── config.ts          # App configuration
├── app.json           # Expo configuration
└── package.json
```

## Configuration

Update `config.ts` with your backend API URL:

```typescript
export const API_URL = 'http://localhost:5000';
export const WS_URL = 'ws://localhost:5000';
```

## Building for Production

### iOS

```bash
npm run build -- --platform ios
```

### Android

```bash
npm run build -- --platform android
```

## API Integration

The app connects to the eBay Agent Cockpit backend API with the following endpoints:

- `GET /api/alerts` - List user alerts
- `POST /api/alerts` - Create new alert
- `GET /api/analytics/dashboard` - Get analytics data
- `GET /api/ml/forecast/{alert_id}` - Get price forecast
- `GET /api/users/profile` - Get user profile

## Push Notifications

Push notifications are configured using Expo Notifications:

```typescript
import * as Notifications from 'expo-notifications';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});
```

## Authentication

Uses token-based authentication stored in AsyncStorage:

```typescript
const { token } = useAuthStore();
// Token automatically included in API headers
```

## Technologies

- **React Native** - Cross-platform framework
- **Expo** - React Native development platform
- **TypeScript** - Type-safe development
- **Zustand** - State management
- **Axios** - HTTP client
- **React Navigation** - Navigation library

## License

MIT
