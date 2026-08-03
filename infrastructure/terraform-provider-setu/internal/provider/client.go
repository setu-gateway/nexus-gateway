package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// client is a minimal REST client for the subset of Setu Gateway's
// dashboard-management API (apps/gateway/api/auth.py, projects.py, keys.py) this
// provider needs. It logs in once during Configure and retries a request exactly
// once after a fresh login if the access token has expired mid-run - the same
// posture as the dashboard's own apps/dashboard/src/lib/api.ts, since a
// `terraform apply` can easily outlast a 15-minute access token.
type client struct {
	httpClient   *http.Client
	endpoint     string
	email        string
	password     string
	accessToken  string
	refreshToken string
}

func newClient(endpoint, email, password string) *client {
	return &client{
		httpClient: &http.Client{Timeout: 30 * time.Second},
		endpoint:   endpoint,
		email:      email,
		password:   password,
	}
}

type loginResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
}

func (c *client) login(ctx context.Context) error {
	body, _ := json.Marshal(map[string]string{"email": c.email, "password": c.password})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint+"/auth/login", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("could not reach %s: %w", c.endpoint, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("login failed (%d): %s", resp.StatusCode, string(respBody))
	}

	var out loginResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return fmt.Errorf("decoding login response: %w", err)
	}
	c.accessToken = out.AccessToken
	c.refreshToken = out.RefreshToken
	return nil
}

// request performs one authenticated call, re-logging in and retrying exactly once
// on a 401 (mirrors apps/dashboard/src/lib/api.ts's single-retry-then-give-up
// posture rather than looping indefinitely on a real auth failure).
func (c *client) request(ctx context.Context, method, path string, body any, out any) error {
	if c.accessToken == "" {
		if err := c.login(ctx); err != nil {
			return err
		}
	}

	statusCode, respBody, err := c.doOnce(ctx, method, path, body)
	if err != nil {
		return err
	}
	if statusCode == http.StatusUnauthorized {
		if err := c.login(ctx); err != nil {
			return fmt.Errorf("session expired and re-login failed: %w", err)
		}
		statusCode, respBody, err = c.doOnce(ctx, method, path, body)
		if err != nil {
			return err
		}
	}

	if statusCode >= 300 {
		return fmt.Errorf("%s %s failed (%d): %s", method, path, statusCode, string(respBody))
	}
	if out != nil && len(respBody) > 0 {
		if err := json.Unmarshal(respBody, out); err != nil {
			return fmt.Errorf("decoding response from %s %s: %w", method, path, err)
		}
	}
	return nil
}

func (c *client) doOnce(ctx context.Context, method, path string, body any) (int, []byte, error) {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return 0, nil, err
		}
		reader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.endpoint+path, reader)
	if err != nil {
		return 0, nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.accessToken)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return 0, nil, fmt.Errorf("could not reach %s: %w", c.endpoint, err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return resp.StatusCode, nil, err
	}
	return resp.StatusCode, respBody, nil
}

// --- Projects (apps/gateway/api/projects.py) ---------------------------------------

type projectResource struct {
	ID             string  `json:"id"`
	Name           string  `json:"name"`
	OrganizationID string  `json:"organization_id"`
	Description    *string `json:"description"`
}

func (c *client) createProject(ctx context.Context, name, organizationID string, description *string) (*projectResource, error) {
	var out projectResource
	body := map[string]any{"name": name, "organization_id": organizationID}
	if description != nil {
		body["description"] = *description
	}
	if err := c.request(ctx, http.MethodPost, "/projects", body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *client) getProject(ctx context.Context, id string) (*projectResource, error) {
	var out projectResource
	if err := c.request(ctx, http.MethodGet, "/projects/"+id, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *client) updateProject(ctx context.Context, id string, name *string, description *string) (*projectResource, error) {
	var out projectResource
	body := map[string]any{}
	if name != nil {
		body["name"] = *name
	}
	if description != nil {
		body["description"] = *description
	}
	if err := c.request(ctx, http.MethodPatch, "/projects/"+id, body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *client) deleteProject(ctx context.Context, id string) error {
	return c.request(ctx, http.MethodDelete, "/projects/"+id, nil, nil)
}

// --- API keys (apps/gateway/api/keys.py) --------------------------------------------

type apiKeyCreatedResource struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	ProjectID string `json:"project_id"`
	Key       string `json:"key"`
	MaskedKey string `json:"masked_key"`
}

type apiKeyResource struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	ProjectID string `json:"project_id"`
	MaskedKey string `json:"masked_key"`
}

func (c *client) createAPIKey(ctx context.Context, projectID, name string) (*apiKeyCreatedResource, error) {
	var out apiKeyCreatedResource
	body := map[string]any{"project_id": projectID, "name": name}
	if err := c.request(ctx, http.MethodPost, "/keys", body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *client) getAPIKey(ctx context.Context, id string) (*apiKeyResource, error) {
	var out apiKeyResource
	if err := c.request(ctx, http.MethodGet, "/keys/"+id, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *client) deleteAPIKey(ctx context.Context, id string) error {
	return c.request(ctx, http.MethodDelete, "/keys/"+id, nil, nil)
}
