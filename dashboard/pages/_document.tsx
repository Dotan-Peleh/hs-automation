import Document, { Html, Head, Main, NextScript } from 'next/document';

export default class MyDocument extends Document {
  render() {
    // Provide a data-URL SVG favicon so the browser doesn't request /favicon.ico
    const svgFavicon =
      'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2228%22 fill=%22%238b5cf6%22/%3E%3Ctext x=%2232%22 y=%2239%22 text-anchor=%22middle%22 font-size=%2232%22 fill=%22white%22 font-family=%22Arial,sans-serif%22%3EHS%3C/text%3E%3C/svg%3E';
    return (
      <Html lang="en">
        <Head>
          <link rel="icon" href={svgFavicon} type="image/svg+xml" />
        </Head>
        <body>
          <Main />
          <NextScript />
        </body>
      </Html>
    );
  }
}



